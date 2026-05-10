# src/backtest/runner.py
"""Walk-forward backtest orchestrator with multi-pool validation."""

import json
from datetime import datetime
import math
from pathlib import Path
import re
from typing import Optional
import uuid

import pandas as pd

from src.backtest.attribution import (
    compute_baseline,
    summarize_events,
    summarize_signals,
)
from src.backtest.data_sources import (
    BacktestMode,
    MOCK_PROFILE,
    SourcePolicyError,
    TIINGO_PROFILE,
    YFINANCE_PROFILE,
    validate_source_for_mode,
)
from src.backtest.data_loader import DATA_DIR, load_ohlc
from src.backtest.events_db import (
    get_events,
    get_fetch_log_entries,
    get_trusted_events_for_backtest,
    init_db,
)
from src.backtest.features_v2 import build_features_v2
from src.backtest.mock_dataset import (
    MOCK_DATA_MODE,
    MOCK_SCOPE,
    build_mock_factor_frame,
    build_mock_ohlc_frame,
    is_mock_backtest_ticker,
    mock_run_metadata,
)
from src.backtest.multifactor_strategy import (
    generate_mock_multifactor_signals,
    generate_real_multifactor_signals,
    normalize_real_multifactor_strategy_config,
    real_multifactor_formula,
    summarize_factor_attribution,
)
from src.backtest.result_store import RESULTS_DIR, load_run_payload
from src.backtest.signals import align_events_to_trading_dates, generate_signals
from src.backtest.strategy import apply_strategy
from src.backtest.strategy_registry import (
    EVENT_BASELINE,
    MOCK_MULTIFACTOR_DEMO,
    MULTIFACTOR_SCORE,
    StrategyAccessError,
    default_strategy_for_kline,
    validate_strategy_access,
)
from src.backtest.metrics import compute_metrics, compute_event_car
from src.backtest.price_snapshot import load_prices_daily_ohlc
from src.kline.event_filter import filter_backtest_events

TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")


POOLS = {
    "core": {
        "description": "Large-cap biotech (5-15 tickers)",
        "tickers": ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "ALNY", "BMRN"],
    },
    "mid": {
        "description": "XBI/IBB components (30-50 tickers)",
        "tickers": [],
    },
}
REAL_PRICE_SOURCE_PROFILES = {
    YFINANCE_PROFILE.source_id: YFINANCE_PROFILE,
    TIINGO_PROFILE.source_id: TIINGO_PROFILE,
}


def run_single_ticker(
    ticker: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    all_events_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Run backtest for a single ticker over a train/test split.

    Returns:
        Dict with ticker, metrics, and equity curve.
    """
    ohlc = load_ohlc(ticker)
    if ohlc.empty:
        return {"ticker": ticker, "error": "no OHLC data"}

    ohlc["date"] = pd.to_datetime(ohlc["date"])
    events = get_events(ticker, start_date=train_start, end_date=test_end)

    if all_events_df is None:
        all_events_df = events

    train_ohlc = ohlc[(ohlc["date"] >= train_start) & (ohlc["date"] <= train_end)]
    train_events = events[
        pd.to_datetime(events["date"]).between(train_start, train_end)
    ]

    features = build_features_v2(train_ohlc, train_events, all_events_df)
    if features.empty:
        return {"ticker": ticker, "error": "insufficient training data"}

    test_ohlc = ohlc[(ohlc["date"] >= test_start) & (ohlc["date"] <= test_end)]
    test_events = events[pd.to_datetime(events["date"]).between(test_start, test_end)]

    signals = generate_signals(test_ohlc, test_events)
    results = apply_strategy(test_ohlc, signals)
    metrics = compute_metrics(results)

    car_df = compute_event_car(test_ohlc, test_events)

    return {
        "ticker": ticker,
        "train_period": f"{train_start} → {train_end}",
        "test_period": f"{test_start} → {test_end}",
        "metrics": metrics,
        "event_car_summary": {
            "n_events": len(car_df),
            "mean_car": round(car_df["car"].mean(), 4) if not car_df.empty else None,
            "significant_events": (
                int((car_df["t_stat"].abs() > 1.96).sum()) if not car_df.empty else 0
            ),
        },
    }


def _to_iso_date(value: pd.Timestamp) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _ohlc_cache_path(ticker: str) -> Path:
    return DATA_DIR / f"{ticker}.parquet"


def normalize_kline_ticker(value: object) -> str | None:
    ticker = str(value or "").strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        return None
    return ticker


def _json_safe_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _event_ids_by_date(events: pd.DataFrame) -> dict[str, list[str]]:
    if events.empty or "date" not in events.columns:
        return {}

    ids_by_date: dict[str, list[str]] = {}
    for _, row in events.iterrows():
        event_id = row.get("event_id")
        if pd.isna(event_id) or event_id in (None, ""):
            event_id = row.get("id")
        if pd.isna(event_id) or event_id in (None, ""):
            continue

        event_date = _to_iso_date(row["date"])
        ids_by_date.setdefault(event_date, []).append(str(event_id))

    return ids_by_date


def _event_identifier(row: pd.Series) -> str | None:
    event_id = _clean_text(row.get("event_id"))
    if event_id is None:
        event_id = _clean_text(row.get("id"))
    return event_id


def _input_event_ids(events: pd.DataFrame) -> list[str]:
    if events.empty:
        return []

    event_ids: list[str] = []
    for _, row in events.iterrows():
        event_id = _event_identifier(row)
        if event_id is not None:
            event_ids.append(event_id)
    return event_ids


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _count_event_values(events: pd.DataFrame, column: str) -> list[dict]:
    if events.empty or column not in events.columns:
        return []

    counts: dict[str, int] = {}
    for value in events[column]:
        label = _clean_text(value) or "unknown"
        counts[label] = counts.get(label, 0) + 1

    return [
        {column: label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def _trust_summary(events: pd.DataFrame) -> dict:
    return {
        "trusted_event_count": int(len(events)),
        "by_source": _count_event_values(events, "source"),
        "by_ownership_status": _count_event_values(events, "ownership_status"),
    }


def _price_basis(*, use_mock_ohlc: bool, source_id: str) -> str:
    if use_mock_ohlc:
        return "demo_ohlc"
    if source_id == TIINGO_PROFILE.source_id:
        return "research_snapshot_adjusted_ohlc"
    return "visible_ohlc"


def _serialize_signals(signals: pd.DataFrame, events: pd.DataFrame) -> list[dict]:
    if signals.empty or "date" not in signals.columns:
        return []

    ids_by_date = _event_ids_by_date(events)
    serialized = []
    for row in signals.itertuples(index=False):
        signal_date = _to_iso_date(getattr(row, "date"))
        signal_value = _json_safe_number(getattr(row, "signal", 0))
        signal_strength = _json_safe_number(getattr(row, "signal_strength", 0.0))
        serialized.append(
            {
                "date": signal_date,
                "signal": int(signal_value or 0),
                "signal_strength": signal_strength or 0.0,
                "source_event_ids": ids_by_date.get(signal_date, []),
            }
        )

    return serialized


def _trade_pnl_pct(direction: str, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if direction == "short":
        return (entry_price - exit_price) / entry_price
    return exit_price / entry_price - 1


def _derive_trades(price_window: pd.DataFrame, results: pd.DataFrame) -> list[dict]:
    """Serialize continuous position spans as chart trade overlays."""
    if price_window.empty or results.empty:
        return []
    required_price_columns = {"date", "open", "close"}
    required_result_columns = {"date", "position"}
    if not required_price_columns.issubset(price_window.columns):
        return []
    if not required_result_columns.issubset(results.columns):
        return []

    prices = price_window[["date", "open", "close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"])
    result_columns = ["date", "position"]
    if "daily_return" in results.columns:
        result_columns.append("daily_return")
    positions = results[result_columns].copy()
    positions["date"] = pd.to_datetime(positions["date"])
    rows = (
        prices.merge(positions, on="date", how="inner")
        .sort_values("date")
        .reset_index(drop=True)
    )
    if rows.empty:
        return []

    trades: list[dict] = []
    open_trade: dict | None = None

    def close_trade(exit_row: pd.Series) -> None:
        nonlocal open_trade
        if open_trade is None:
            return

        entry_price = float(open_trade["entry_price"])
        exit_price = _json_safe_number(exit_row["close"])
        if exit_price is None:
            open_trade = None
            return

        direction = str(open_trade["direction"])
        pnl_pct = None
        if "daily_return" in rows.columns:
            span = rows.iloc[int(open_trade["_start_index"]) : int(exit_row.name) + 1]
            weighted_returns = []
            for span_row in span.itertuples(index=False):
                position = _json_safe_number(getattr(span_row, "position", 0.0))
                daily_return = _json_safe_number(getattr(span_row, "daily_return", 0.0))
                if position is None or position == 0 or daily_return is None:
                    continue
                weighted_returns.append(daily_return / abs(position))
            if weighted_returns:
                compounded = 1.0
                for value in weighted_returns:
                    compounded *= 1 + value
                pnl_pct = compounded - 1

        if pnl_pct is None:
            pnl_pct = _trade_pnl_pct(direction, entry_price, exit_price)

        trades.append(
            {
                "entry_date": open_trade["entry_date"],
                "exit_date": _to_iso_date(exit_row["date"]),
                "direction": direction,
                "size": open_trade["size"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 6),
            }
        )
        open_trade = None

    for index, row in rows.iterrows():
        position = _json_safe_number(row["position"])
        if position is None:
            continue

        current_direction = "long" if position > 0 else "short" if position < 0 else None
        if current_direction is None:
            if open_trade is not None:
                previous_row = rows.iloc[max(index - 1, int(open_trade["_start_index"]))]
                close_trade(previous_row)
            continue

        if (
            open_trade is not None
            and (
                open_trade["direction"] != current_direction
                or not math.isclose(float(open_trade["size"]), abs(position), rel_tol=1e-9, abs_tol=1e-12)
            )
        ):
            previous_row = rows.iloc[max(index - 1, int(open_trade["_start_index"]))]
            close_trade(previous_row)

        if open_trade is not None:
            continue

        entry_price = _json_safe_number(row["open"])
        if entry_price is None:
            continue
        direction = "long" if position > 0 else "short"
        open_trade = {
            "_start_index": index,
            "entry_date": _to_iso_date(row["date"]),
            "direction": direction,
            "size": abs(position),
            "entry_price": entry_price,
        }

    if open_trade is not None:
        close_trade(rows.iloc[-1])

    return trades


def _exposure_summary(results: pd.DataFrame, trades: list[dict]) -> dict:
    if results.empty or "position" not in results.columns:
        return {
            "exposure_days": 0,
            "exposure_ratio": 0.0,
            "trade_count": len(trades),
            "avg_abs_position": 0.0,
        }

    positions = pd.to_numeric(results["position"], errors="coerce").fillna(0.0)
    exposed = positions.abs() > 0
    exposure_days = int(exposed.sum())
    total_days = int(len(positions))
    avg_abs_position = float(positions[exposed].abs().mean()) if exposure_days else 0.0
    return {
        "exposure_days": exposure_days,
        "exposure_ratio": round(exposure_days / total_days, 6) if total_days else 0.0,
        "trade_count": len(trades),
        "avg_abs_position": round(avg_abs_position, 6),
    }


def _mock_signal_days_for_window(price_window: pd.DataFrame) -> int:
    if price_window.empty:
        return 8
    return min(60, max(8, math.ceil(len(price_window) / 50)))


def _load_results_index() -> dict:
    index_path = RESULTS_DIR / "index.json"
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            raw_index = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw_index = {}

    latest_by_ticker: dict[str, dict[str, str]] = {}
    if isinstance(raw_index, dict) and isinstance(
        raw_index.get("latest_by_ticker"), dict
    ):
        for ticker, entry in raw_index["latest_by_ticker"].items():
            normalized_ticker = normalize_kline_ticker(ticker)
            if normalized_ticker is None or not isinstance(entry, dict):
                continue

            clean_entry: dict[str, str] = {}
            for key in ("run_id", "ticker", "start", "end", "created_at"):
                text = _clean_text(entry.get(key))
                if text is not None:
                    clean_entry[key] = text
            if clean_entry:
                latest_by_ticker[normalized_ticker] = clean_entry

    return {"latest_by_ticker": latest_by_ticker}


def _update_latest_run_index(payload: dict) -> None:
    index = _load_results_index()
    latest_by_ticker = index["latest_by_ticker"]
    ticker = str(payload["ticker"])
    latest_by_ticker[ticker] = {
        "run_id": str(payload["run_id"]),
        "ticker": ticker,
        "start": str(payload["start_date"]),
        "end": str(payload["end_date"]),
        "created_at": str(payload["created_at"]),
    }

    with open(RESULTS_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, allow_nan=False)


def run_kline_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    report_confidence: float = 1.0,
    strategy_id: str | None = None,
    data_mode: str | None = None,
    backtest_mode: str = "exploratory",
    price_source: str | None = None,
    data_snapshot_id: str | None = None,
    holding_period_days: int | None = None,
    strategy_config: dict | None = None,
    persist_result: bool = True,
) -> dict:
    """Run a single-ticker backtest and persist result as JSON.

    This API is intended for the K-line web workflow and keeps the response
    chart-ready with a flat payload shape.
    """
    normalized_ticker = normalize_kline_ticker(ticker)
    if normalized_ticker is None:
        return {"error": "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"}

    ticker = normalized_ticker
    requested_strategy_id = str(strategy_id).strip() if strategy_id else None
    requested_data_mode = str(data_mode).strip() if data_mode else None
    resolved_strategy_id = requested_strategy_id or default_strategy_for_kline(ticker)
    resolved_data_mode = requested_data_mode or (
        MOCK_DATA_MODE
        if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO
        and is_mock_backtest_ticker(ticker)
        else "real"
    )
    resolved_mock_scope = (
        MOCK_SCOPE
        if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO
        and resolved_data_mode == MOCK_DATA_MODE
        and is_mock_backtest_ticker(ticker)
        else None
    )
    try:
        validate_strategy_access(
            strategy_id=resolved_strategy_id,
            data_mode=resolved_data_mode,
            mock_scope=resolved_mock_scope,
        )
    except StrategyAccessError as exc:
        return {"error": str(exc)}

    resolved_strategy_config = None
    if resolved_strategy_id == MULTIFACTOR_SCORE:
        try:
            resolved_strategy_config = normalize_real_multifactor_strategy_config(
                strategy_config
            )
        except ValueError as exc:
            return {"error": str(exc)}

    use_mock_ohlc = (
        resolved_strategy_id == MOCK_MULTIFACTOR_DEMO
        and resolved_data_mode == MOCK_DATA_MODE
    )

    mode_text = str(backtest_mode).strip() if backtest_mode else "exploratory"
    requested_price_source = str(price_source).strip() if price_source else None
    if (
        use_mock_ohlc
        and requested_price_source == YFINANCE_PROFILE.source_id
    ):
        requested_price_source = None
    if not use_mock_ohlc and requested_price_source is None and data_snapshot_id:
        requested_price_source = TIINGO_PROFILE.source_id
    source_profile = (
        MOCK_PROFILE
        if use_mock_ohlc
        else REAL_PRICE_SOURCE_PROFILES.get(
            requested_price_source or YFINANCE_PROFILE.source_id
        )
    )
    resolved_price_source = requested_price_source or (
        source_profile.source_id if source_profile is not None else None
    )
    if source_profile is None or resolved_price_source != source_profile.source_id:
        return {"error": f"unsupported price_source: {resolved_price_source}"}
    if source_profile.source_id == TIINGO_PROFILE.source_id and not data_snapshot_id:
        return {"error": "data_snapshot_id is required for tiingo price_source"}

    try:
        resolved_mode = BacktestMode.MOCK if use_mock_ohlc else BacktestMode(mode_text)
        source_validation = validate_source_for_mode(source_profile, resolved_mode)
    except (SourcePolicyError, ValueError) as exc:
        return {"error": str(exc)}

    if use_mock_ohlc:
        ohlc = build_mock_ohlc_frame(ticker, start_date, end_date)
        cache_path = None
    elif source_profile.source_id == TIINGO_PROFILE.source_id:
        cache_path = None
        try:
            ohlc = load_prices_daily_ohlc(
                ticker=ticker,
                data_snapshot_id=str(data_snapshot_id),
                source=source_profile.source_id,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"failed to load OHLC snapshot: {exc}"}
    else:
        cache_path = _ohlc_cache_path(ticker)
        try:
            ohlc = load_ohlc(ticker)
        except ModuleNotFoundError as exc:
            return {
                "error": (
                    f"failed to load OHLC: {exc}. "
                    "Use the Python 3.11 project interpreter and install requirements.txt "
                    "in that environment."
                )
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"failed to load OHLC: {exc}"}

    if ohlc.empty:
        if use_mock_ohlc:
            return {"error": "no mock OHLC data"}
        if cache_path is not None and not cache_path.exists():
            return {
                "error": (
                    "no OHLC data. No local cache exists and the online fetch returned "
                    "no rows. Check network access to Yahoo Finance or preload data/ohlc."
                )
            }
        return {"error": "no OHLC data"}

    ohlc = ohlc.copy()
    ohlc["date"] = pd.to_datetime(ohlc["date"])
    price_window = ohlc[
        (ohlc["date"] >= start_date) & (ohlc["date"] <= end_date)
    ].copy()
    if len(price_window) < 2:
        return {"error": "insufficient OHLC data in date range"}

    init_db()
    events = get_trusted_events_for_backtest(
        ticker,
        start_date=start_date,
        end_date=end_date,
    )
    eligible_events, event_filter = filter_backtest_events(events)

    if resolved_strategy_id == EVENT_BASELINE and eligible_events.empty:
        return {"error": "no trusted backtest-eligible events in date range"}

    mock_metadata = None
    factor_attribution = {}
    effective_holding_period_days = (
        holding_period_days
        if holding_period_days is not None
        else 5 if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO else 1
    )
    if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO:
        factors = build_mock_factor_frame(
            ticker,
            price_window,
            min_signal_days=_mock_signal_days_for_window(price_window),
        )
        signals = generate_mock_multifactor_signals(price_window, factors)
        signal_events = align_events_to_trading_dates(eligible_events, price_window)
        factor_attribution = summarize_factor_attribution(factors)
        mock_metadata = mock_run_metadata(ticker)
    elif resolved_strategy_id == MULTIFACTOR_SCORE:
        signal_events = align_events_to_trading_dates(eligible_events, price_window)
        signals = generate_real_multifactor_signals(
            price_window,
            signal_events,
            report_confidence=report_confidence,
            strategy_config=resolved_strategy_config,
        )
    else:
        signal_events = align_events_to_trading_dates(eligible_events, price_window)
        signals = generate_signals(
            price_window, signal_events, report_confidence=report_confidence
        )
    results = apply_strategy(
        price_window,
        signals,
        max_position_pct=max_position_pct,
        stop_loss_pct=stop_loss_pct,
        slippage_pct=slippage_pct,
        holding_period_days=effective_holding_period_days,
    )

    raw_metrics = compute_metrics(results)
    strategy_metrics = (
        raw_metrics.get("layer3_strategy", {}) if isinstance(raw_metrics, dict) else {}
    )
    metrics = {
        "sharpe": _json_safe_number(strategy_metrics.get("sharpe_ratio")),
        "annualized_return": _json_safe_number(
            strategy_metrics.get("annualized_return")
        ),
        "max_drawdown": _json_safe_number(strategy_metrics.get("max_drawdown")),
        "win_rate": _json_safe_number(strategy_metrics.get("win_rate")),
        "profit_factor": _json_safe_number(strategy_metrics.get("profit_factor")),
    }

    equity_curve = []
    for row in results.itertuples(index=False):
        equity = _json_safe_number(row.equity)
        if equity is None:
            continue
        equity_curve.append(
            {
                "date": _to_iso_date(row.date),
                "equity": equity,
            }
        )

    car_df = compute_event_car(price_window, signal_events)
    event_car = []
    if not car_df.empty:
        for row in car_df.itertuples(index=False):
            event_car.append(
                {
                    "event_id": str(getattr(row, "event_id", "")),
                    "type": str(getattr(row, "event_type", "")),
                    "date": _to_iso_date(getattr(row, "date")),
                    "car": _json_safe_number(getattr(row, "car", 0.0)),
                    "t_stat": _json_safe_number(getattr(row, "t_stat", 0.0)),
                }
            )

    created_at = datetime.now()
    run_id = created_at.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    trades = _derive_trades(price_window, results)
    payload = {
        "run_id": run_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "strategy": {
            "id": resolved_strategy_id,
            "data_mode": resolved_data_mode,
            "holding_period_days": effective_holding_period_days,
            "price_basis": _price_basis(
                use_mock_ohlc=use_mock_ohlc,
                source_id=source_profile.source_id,
            ),
            "config": resolved_strategy_config,
            "formula": (
                real_multifactor_formula(resolved_strategy_config)
                if resolved_strategy_id == MULTIFACTOR_SCORE
                else None
            ),
        },
        "risk_parameters": {
            "stop_loss_pct": stop_loss_pct,
            "max_position_pct": max_position_pct,
            "slippage_pct": slippage_pct,
            "holding_period_days": effective_holding_period_days,
        },
        "mock_metadata": mock_metadata,
        "factor_attribution": factor_attribution,
        "data_snapshot_id": data_snapshot_id,
        "backtest_mode": str(resolved_mode.value),
        "price_source": resolved_price_source,
        "bias_profile": str(source_validation.bias_profile.value),
        "bias_warnings": list(source_validation.bias_warnings),
        "input_event_ids": _input_event_ids(eligible_events),
        "trust_summary": _trust_summary(eligible_events),
        "source_status_at_run": get_fetch_log_entries(ticker),
        "metrics": metrics,
        "equity_curve": equity_curve,
        "event_car": event_car,
        "signals": _serialize_signals(signals, signal_events),
        "trades": trades,
        "exposure_summary": _exposure_summary(results, trades),
        "event_filter": event_filter,
        "event_attribution": summarize_events(eligible_events),
        "signal_summary": summarize_signals(signals),
        "baseline": compute_baseline(price_window, results),
    }

    if persist_result:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_DIR / f"{run_id}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        _update_latest_run_index(payload)

    return payload


def load_saved_run(run_id: str) -> dict | None:
    """Load a persisted single-run backtest payload by run_id."""
    return load_run_payload(run_id, RESULTS_DIR)


def run_walk_forward(
    tickers: list[str],
    start_year: int = 2014,
    end_year: int = 2025,
    train_window: int = 5,
    test_window: int = 1,
) -> dict:
    """Run walk-forward backtest across multiple tickers.

    Walk-forward windows:
        2014-2018 train → 2019 test
        2015-2019 train → 2020 test
        ...

    Returns:
        Dict with per-ticker and aggregate results.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir()

    all_results = []

    for window_start in range(start_year, end_year - train_window - test_window + 2):
        train_start = f"{window_start}-01-01"
        train_end = f"{window_start + train_window - 1}-12-31"
        test_start = f"{window_start + train_window}-01-01"
        test_end = f"{window_start + train_window + test_window - 1}-12-31"

        for ticker in tickers:
            result = run_single_ticker(
                ticker,
                train_start,
                train_end,
                test_start,
                test_end,
            )
            result["window"] = (
                f"{window_start}-{window_start + train_window + test_window - 1}"
            )
            all_results.append(result)

    output = {
        "run_id": run_id,
        "config": {
            "tickers": tickers,
            "start_year": start_year,
            "end_year": end_year,
            "train_window": train_window,
            "test_window": test_window,
        },
        "results": all_results,
    }

    with open(run_dir / "results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    return output


if __name__ == "__main__":
    result = run_walk_forward(POOLS["core"]["tickers"])
    print(f"Backtest complete: {result['run_id']}")
    print(f"Results saved to: {RESULTS_DIR / result['run_id']}")
