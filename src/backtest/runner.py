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
from src.backtest.data_loader import DATA_DIR, load_ohlc
from src.backtest.events_db import (
    get_events,
    get_fetch_log_entries,
    get_trusted_events_for_backtest,
    init_db,
)
from src.backtest.features_v2 import build_features_v2
from src.backtest.signals import generate_signals
from src.backtest.strategy import apply_strategy
from src.backtest.metrics import compute_metrics, compute_event_car
from src.kline.event_filter import filter_backtest_events

RESULTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "backtest_results"
)
RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")
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
    """Serialize per-exposure trade overlays from strategy result rows.

    `apply_strategy()` models each non-zero result row as exposure from that
    day's open to that day's close, so the chart overlay should not combine
    consecutive same-direction rows into a synthetic multi-day PnL span.
    """
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
    for _, row in rows.iterrows():
        position = _json_safe_number(row["position"])
        if position is None or position == 0:
            continue

        entry_price = _json_safe_number(row["open"])
        exit_price = _json_safe_number(row["close"])
        if entry_price is None or exit_price is None:
            continue

        direction = "long" if position > 0 else "short"
        daily_return = (
            _json_safe_number(row.get("daily_return"))
            if "daily_return" in rows.columns
            else None
        )
        if daily_return is not None:
            pnl_pct = daily_return / abs(position)
        else:
            pnl_pct = _trade_pnl_pct(direction, entry_price, exit_price)
        trades.append(
            {
                "entry_date": _to_iso_date(row["date"]),
                "exit_date": _to_iso_date(row["date"]),
                "direction": direction,
                "size": abs(position),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 6),
            }
        )

    return trades


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
    report_confidence: float = 0.5,
) -> dict:
    """Run a single-ticker backtest and persist result as JSON.

    This API is intended for the K-line web workflow and keeps the response
    chart-ready with a flat payload shape.
    """
    normalized_ticker = normalize_kline_ticker(ticker)
    if normalized_ticker is None:
        return {"error": "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"}

    ticker = normalized_ticker
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
        if not cache_path.exists():
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
    if events.empty:
        return {"error": "no trusted backtest-eligible events in date range"}

    eligible_events, event_filter = filter_backtest_events(events)
    signals = generate_signals(
        price_window, eligible_events, report_confidence=report_confidence
    )
    results = apply_strategy(
        price_window,
        signals,
        max_position_pct=max_position_pct,
        stop_loss_pct=stop_loss_pct,
        slippage_pct=slippage_pct,
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

    car_df = compute_event_car(price_window, eligible_events)
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
    payload = {
        "run_id": run_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "input_event_ids": _input_event_ids(eligible_events),
        "trust_summary": _trust_summary(eligible_events),
        "source_status_at_run": get_fetch_log_entries(ticker),
        "metrics": metrics,
        "equity_curve": equity_curve,
        "event_car": event_car,
        "signals": _serialize_signals(signals, eligible_events),
        "trades": _derive_trades(price_window, results),
        "event_filter": event_filter,
        "event_attribution": summarize_events(eligible_events),
        "signal_summary": summarize_signals(signals),
        "baseline": compute_baseline(price_window, results),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / f"{run_id}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
    _update_latest_run_index(payload)

    return payload


def load_saved_run(run_id: str) -> dict | None:
    """Load a persisted single-run backtest payload by run_id."""
    if not RUN_ID_PATTERN.fullmatch(str(run_id or "")):
        return None

    path = RESULTS_DIR / f"{run_id}.json"
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


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
