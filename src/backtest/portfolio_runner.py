"""Portfolio-level K-line backtest aggregation for the biotech K-line universe."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import uuid

from src.backtest.data_sources import (
    BacktestMode,
    TIINGO_PROFILE,
    validate_source_for_mode,
)
from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.runner import normalize_kline_ticker, run_kline_backtest
from src.backtest.strategy_registry import StrategyAccessError, validate_strategy_access
from src.backtest.universe import UnsupportedUniverseError, load_universe_tickers
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID

BIOTECH_REAL_UNIVERSE_ID = BIOTECH_US_UNIVERSE_ID
REAL_MULTIFACTOR_STRATEGY_ID = "multifactor_score"
REAL_PORTFOLIO_DATA_MODE = "real"
DISCLOSURE_KEYS = {
    "mock_metadata",
    "synthetic",
    "data_mode",
    "positive_demo_expected",
    "mock",
}


def _data_credibility(
    *,
    eligible_universe_count: int,
    skipped_ticker_count: int = 0,
    coverage_status: str | None = None,
) -> dict:
    payload = {
        "eligible_universe_count": eligible_universe_count,
        "skipped_ticker_count": skipped_ticker_count,
        "survivorship_bias_warning": True,
        "universe_bias_status": "current_constituents_only",
    }
    if coverage_status is not None:
        payload["coverage_status"] = coverage_status
    return payload


def _real_universe_error_payload(
    *,
    error: str,
    universe_id: str,
    data_snapshot_id: str | None,
    as_of_date: str,
    start_date: str,
    end_date: str,
    coverage_status: str,
) -> dict:
    return {
        "error": error,
        "universe_id": universe_id,
        "data_snapshot_id": data_snapshot_id,
        "as_of_date": as_of_date,
        "start_date": start_date,
        "end_date": end_date,
        "data_credibility": _data_credibility(
            eligible_universe_count=0,
            coverage_status=coverage_status,
        ),
    }


def _without_disclosure_keys(value):
    if isinstance(value, dict):
        return {
            key: _without_disclosure_keys(child)
            for key, child in value.items()
            if not any(disclosure in key.lower() for disclosure in DISCLOSURE_KEYS)
        }
    if isinstance(value, list):
        return [_without_disclosure_keys(child) for child in value]
    if isinstance(value, str) and any(
        disclosure in value.lower() for disclosure in DISCLOSURE_KEYS
    ):
        return None
    return value


def _strategy_return(payload: dict) -> float | None:
    baseline = payload.get("baseline")
    if isinstance(baseline, dict) and baseline.get("strategy_return") is not None:
        return round(float(baseline["strategy_return"]), 6)

    equity_curve = payload.get("equity_curve")
    if isinstance(equity_curve, list) and equity_curve:
        first_equity = float(equity_curve[0].get("equity", 0.0))
        last_equity = float(equity_curve[-1].get("equity", 0.0))
        if first_equity:
            return round(last_equity / first_equity - 1.0, 6)
    return None


def _active_signal_days(payload: dict) -> int:
    signal_summary = payload.get("signal_summary")
    if isinstance(signal_summary, dict):
        return int(signal_summary.get("active_signal_days") or 0)

    signals = payload.get("signals")
    if isinstance(signals, list):
        return sum(1 for signal in signals if signal.get("signal"))
    return 0


def _equity_by_date(payload: dict) -> dict[str, float]:
    equity_curve = payload.get("equity_curve")
    if not isinstance(equity_curve, list) or not equity_curve:
        return {}

    base_equity = None
    for point in equity_curve:
        try:
            candidate = float(point.get("equity", 0.0))
        except (AttributeError, TypeError, ValueError):
            continue
        if candidate > 0:
            base_equity = candidate
            break
    if base_equity is None:
        return {}

    values = {}
    for point in equity_curve:
        if not isinstance(point, dict):
            continue
        date = str(point.get("date") or "").strip()
        if not date:
            continue
        values[date] = float(point.get("equity", 0.0)) / base_equity
    return values


def _portfolio_equity_curve(constituent_payloads: list[dict]) -> list[dict]:
    values_by_date: dict[str, list[float]] = {}
    for payload in constituent_payloads:
        for date, equity in _equity_by_date(payload).items():
            values_by_date.setdefault(date, []).append(equity)

    return [
        {
            "date": date,
            "equity": round(sum(values) / len(values), 6),
        }
        for date, values in sorted(values_by_date.items())
        if values
    ]


def _constituent_row(payload: dict) -> dict:
    trades = payload.get("trades")
    trade_count = len(trades) if isinstance(trades, list) else 0
    return _without_disclosure_keys(
        {
            "ticker": payload.get("ticker"),
            "strategy_return": _strategy_return(payload),
            "active_signal_days": _active_signal_days(payload),
            "trade_count": trade_count,
            "metrics": payload.get("metrics", {}),
            "baseline": payload.get("baseline", {}),
            "factor_attribution": payload.get("factor_attribution", {}),
            "exposure_summary": payload.get("exposure_summary", {}),
        }
    )


def _focus_payload(payload: dict) -> dict:
    return _without_disclosure_keys(
        {
            "ticker": payload.get("ticker"),
            "equity_curve": payload.get("equity_curve", []),
            "signals": payload.get("signals", []),
            "trades": payload.get("trades", []),
            "metrics": payload.get("metrics", {}),
            "baseline": payload.get("baseline", {}),
            "factor_attribution": payload.get("factor_attribution", {}),
            "exposure_summary": payload.get("exposure_summary", {}),
        }
    )


def _portfolio_metrics(
    portfolio_equity_curve: list[dict],
    constituents: list[dict],
) -> dict:
    strategy_return = None
    if portfolio_equity_curve:
        strategy_return = round(float(portfolio_equity_curve[-1]["equity"]) - 1.0, 6)

    ranked = [
        row for row in constituents if row.get("strategy_return") is not None
    ]
    best = max(ranked, key=lambda row: row["strategy_return"]) if ranked else {}
    worst = min(ranked, key=lambda row: row["strategy_return"]) if ranked else {}
    total_trades = sum(int(row.get("trade_count") or 0) for row in constituents)
    avg_active_signal_days = 0.0
    if constituents:
        avg_active_signal_days = round(
            sum(int(row.get("active_signal_days") or 0) for row in constituents)
            / len(constituents),
            6,
        )
    avg_exposure_days = 0.0
    if constituents:
        avg_exposure_days = round(
            sum(
                int((row.get("exposure_summary") or {}).get("exposure_days") or 0)
                for row in constituents
            )
            / len(constituents),
            6,
        )

    return {
        "strategy_return": strategy_return,
        "best_ticker": best.get("ticker"),
        "worst_ticker": worst.get("ticker"),
        "total_trades": total_trades,
        "avg_active_signal_days": avg_active_signal_days,
        "avg_exposure_days": avg_exposure_days,
    }


def _data_snapshot_metadata(
    data_snapshot_id: str | None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, str | None] | None:
    if not data_snapshot_id:
        return None

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    import duckdb

    conn = duckdb.connect(str(path), read_only=True)
    try:
        row = conn.execute(
            """
            SELECT
                CAST(snapshot_date AS VARCHAR),
                CAST(price_source AS VARCHAR),
                CAST(universe_id AS VARCHAR),
                CAST(bias_profile AS VARCHAR)
            FROM data_snapshots
            WHERE data_snapshot_id = ?
            """,
            [str(data_snapshot_id).strip()],
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return {
        "snapshot_date": row[0],
        "price_source": row[1],
        "universe_id": row[2],
        "bias_profile": row[3],
    }


def _is_snapshot_price_gap(error: object) -> bool:
    message = str(error or "").lower()
    return (
        "no ohlc data" in message
        or "insufficient ohlc data" in message
        or "failed to load ohlc snapshot" in message
    )


def _json_payload(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _persist_portfolio_backtest_run(
    payload: dict,
    *,
    db_path: str | Path | None,
    data_snapshot_id: str,
    universe_id: str,
    strategy_id: str,
    bias_profile: str,
    bias_warnings: tuple[str, ...],
    start_date: str,
    end_date: str,
    as_of_date: str,
    price_source: str,
    focus_ticker: str,
) -> None:
    if payload.get("error"):
        return

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    parameters = {
        "focus_ticker": normalize_kline_ticker(focus_ticker),
        "start_date": start_date,
        "end_date": end_date,
        "as_of_date": as_of_date,
        "price_source": price_source,
        "risk_parameters": payload.get("risk_parameters", {}),
        "eligible_tickers": payload.get("eligible_tickers", []),
        "completed_tickers": payload.get("tickers", []),
        "skipped_tickers": payload.get("skipped_tickers", []),
    }
    coverage = {
        **(payload.get("data_credibility") or {}),
        "completed_ticker_count": len(payload.get("tickers") or []),
        "skipped_tickers": payload.get("skipped_tickers", []),
    }

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("DELETE FROM backtest_runs WHERE run_id = ?", [payload["run_id"]])
        conn.execute(
            """
            INSERT INTO backtest_runs (
                run_id,
                data_snapshot_id,
                universe_id,
                split_id,
                strategy_id,
                data_mode,
                bias_profile,
                parameters_json,
                metrics_json,
                coverage_json,
                bias_warnings_json,
                created_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                payload["run_id"],
                data_snapshot_id,
                universe_id,
                None,
                strategy_id,
                REAL_PORTFOLIO_DATA_MODE,
                bias_profile,
                _json_payload(parameters),
                _json_payload(payload.get("portfolio_metrics", {})),
                _json_payload(coverage),
                _json_payload(list(bias_warnings)),
                payload.get("created_at"),
                datetime.now().isoformat(timespec="seconds"),
            ],
        )
    finally:
        conn.close()


def _run_biotech_portfolio_backtest(
    focus_ticker: str,
    start_date: str,
    end_date: str,
    *,
    universe_id: str,
    tickers: tuple[str, ...],
    strategy_id: str,
    data_mode: str,
    as_of_date: str | None = None,
    data_snapshot_id: str | None = None,
    price_source: str | None = None,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    holding_period_days: int | None = None,
) -> dict:
    normalized_focus_ticker = normalize_kline_ticker(focus_ticker)
    if normalized_focus_ticker not in tickers:
        normalized_focus_ticker = tickers[0]

    resolved_holding_period_days = holding_period_days or 5
    runs = []
    skipped_tickers = []
    for ticker in tickers:
        payload = run_kline_backtest(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            stop_loss_pct=stop_loss_pct,
            max_position_pct=max_position_pct,
            slippage_pct=slippage_pct,
            holding_period_days=resolved_holding_period_days,
            strategy_id=strategy_id,
            data_mode=data_mode,
            price_source=price_source,
            data_snapshot_id=data_snapshot_id,
        )
        if isinstance(payload, dict) and payload.get("error"):
            if data_snapshot_id is not None and _is_snapshot_price_gap(payload.get("error")):
                skipped_tickers.append(
                    {
                        "ticker": ticker,
                        "reason": str(payload.get("error")),
                    }
                )
                continue
            error_payload = {"error": f"{ticker}: {payload.get('error')}"}
            if data_snapshot_id is not None:
                error_payload["universe_id"] = universe_id
                error_payload["data_snapshot_id"] = data_snapshot_id
                error_payload["skipped_tickers"] = skipped_tickers
            return error_payload
        runs.append(payload)

    if not runs:
        return {
            "error": f"no tickers with price coverage for data snapshot {data_snapshot_id}",
            "universe_id": universe_id,
            "data_snapshot_id": data_snapshot_id,
            "as_of_date": as_of_date,
            "start_date": start_date,
            "end_date": end_date,
            "skipped_tickers": skipped_tickers,
        }

    completed_tickers = tuple(str(payload.get("ticker")) for payload in runs)
    if normalized_focus_ticker not in completed_tickers:
        normalized_focus_ticker = completed_tickers[0]

    portfolio_equity_curve = _portfolio_equity_curve(runs)
    constituents = [_constituent_row(payload) for payload in runs]
    focus_run = next(
        payload for payload in runs if payload.get("ticker") == normalized_focus_ticker
    )
    created_at = datetime.now()

    return {
        "run_id": created_at.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8],
        "created_at": created_at.isoformat(timespec="seconds"),
        "universe_id": universe_id,
        "data_snapshot_id": data_snapshot_id,
        "as_of_date": as_of_date,
        "tickers": list(completed_tickers),
        "eligible_tickers": list(tickers),
        "skipped_tickers": skipped_tickers,
        "start_date": start_date,
        "end_date": end_date,
        "strategy": {"id": strategy_id},
        "risk_parameters": {
            "stop_loss_pct": stop_loss_pct,
            "max_position_pct": max_position_pct,
            "slippage_pct": slippage_pct,
            "holding_period_days": resolved_holding_period_days,
        },
        "portfolio_equity_curve": portfolio_equity_curve,
        "portfolio_metrics": _portfolio_metrics(portfolio_equity_curve, constituents),
        "constituents": constituents,
        "focus_ticker": _focus_payload(focus_run),
    }


def run_real_biotech_portfolio_backtest(
    focus_ticker: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    holding_period_days: int | None = None,
    *,
    db_path: str | Path | None = None,
    universe_id: str = BIOTECH_REAL_UNIVERSE_ID,
    as_of_date: str | None = None,
    data_snapshot_id: str | None = None,
    price_source: str | None = None,
    strategy_id: str | None = None,
) -> dict:
    """Run the real multifactor strategy across the active biotech universe."""
    if not data_snapshot_id:
        return _real_universe_error_payload(
            error="data_snapshot_id is required for portfolio backtests",
            universe_id=universe_id,
            data_snapshot_id=None,
            as_of_date=as_of_date or end_date,
            start_date=start_date,
            end_date=end_date,
            coverage_status="missing_data_snapshot",
        )

    resolved_price_source = str(price_source or TIINGO_PROFILE.source_id).strip()
    if resolved_price_source != TIINGO_PROFILE.source_id:
        return _real_universe_error_payload(
            error="portfolio backtests require tiingo snapshot prices",
            universe_id=universe_id,
            data_snapshot_id=data_snapshot_id,
            as_of_date=as_of_date or end_date,
            start_date=start_date,
            end_date=end_date,
            coverage_status="invalid_price_source",
        )

    resolved_strategy_id = str(strategy_id or REAL_MULTIFACTOR_STRATEGY_ID).strip()
    if not resolved_strategy_id:
        resolved_strategy_id = REAL_MULTIFACTOR_STRATEGY_ID
    try:
        validate_strategy_access(
            strategy_id=resolved_strategy_id,
            data_mode="real",
            mock_scope=None,
        )
    except StrategyAccessError as exc:
        return {"error": str(exc)}

    snapshot_metadata = _data_snapshot_metadata(data_snapshot_id, db_path=db_path)
    source_validation = validate_source_for_mode(
        TIINGO_PROFILE,
        BacktestMode.EXPLORATORY,
    )
    resolved_as_of_date = (
        as_of_date
        or (
            snapshot_metadata.get("snapshot_date")
            if snapshot_metadata is not None
            else None
        )
        or end_date
    )
    try:
        tickers = load_universe_tickers(
            db_path=db_path,
            universe_id=universe_id,
            as_of_date=resolved_as_of_date,
        )
    except UnsupportedUniverseError as exc:
        return _real_universe_error_payload(
            error=str(exc),
            universe_id=universe_id,
            data_snapshot_id=data_snapshot_id,
            as_of_date=resolved_as_of_date,
            start_date=start_date,
            end_date=end_date,
            coverage_status="unsupported_universe",
        )
    except ValueError as exc:
        return _real_universe_error_payload(
            error=str(exc),
            universe_id=universe_id,
            data_snapshot_id=data_snapshot_id,
            as_of_date=resolved_as_of_date,
            start_date=start_date,
            end_date=end_date,
            coverage_status="invalid_as_of_date",
        )

    if not tickers:
        return _real_universe_error_payload(
            error=(
                f"no active tickers found for universe {universe_id} "
                f"as of {resolved_as_of_date}"
            ),
            universe_id=universe_id,
            data_snapshot_id=data_snapshot_id,
            as_of_date=resolved_as_of_date,
            start_date=start_date,
            end_date=end_date,
            coverage_status="no_active_members",
        )

    payload = _run_biotech_portfolio_backtest(
        focus_ticker=focus_ticker,
        start_date=start_date,
        end_date=end_date,
        universe_id=universe_id,
        data_snapshot_id=data_snapshot_id,
        price_source=resolved_price_source,
        tickers=tickers,
        strategy_id=resolved_strategy_id,
        data_mode=REAL_PORTFOLIO_DATA_MODE,
        as_of_date=resolved_as_of_date,
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        slippage_pct=slippage_pct,
        holding_period_days=holding_period_days,
    )
    skipped_count = len(payload.get("skipped_tickers") or [])
    coverage_status = (
        "no_price_coverage"
        if payload.get("error") and skipped_count
        else "partial_price_coverage" if skipped_count else "complete"
    )
    payload["data_credibility"] = _data_credibility(
        eligible_universe_count=len(tickers),
        skipped_ticker_count=skipped_count,
        coverage_status=coverage_status,
    )
    _persist_portfolio_backtest_run(
        payload,
        db_path=db_path,
        data_snapshot_id=data_snapshot_id,
        universe_id=universe_id,
        strategy_id=resolved_strategy_id,
        bias_profile=(
            str(snapshot_metadata.get("bias_profile"))
            if snapshot_metadata and snapshot_metadata.get("bias_profile")
            else str(source_validation.bias_profile.value)
        ),
        bias_warnings=source_validation.bias_warnings,
        start_date=start_date,
        end_date=end_date,
        as_of_date=resolved_as_of_date,
        price_source=resolved_price_source,
        focus_ticker=focus_ticker,
    )
    return payload
