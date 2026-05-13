"""Flask routes for the K-line workspace and backtest APIs."""

from __future__ import annotations

import math
import re
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from src.backtest.portfolio_runner import run_real_biotech_portfolio_backtest
from src.backtest.research_db import (
    RESEARCH_DB_PATH,
    RESEARCH_DIR,
    initialize_research_database,
)
from src.backtest.runner import (
    load_saved_run,
    normalize_kline_ticker,
    run_kline_backtest,
)
from src.backtest.multifactor_strategy import (
    StrategyConfigError,
    normalize_real_multifactor_strategy_config,
)
from src.backtest.strategy_registry import EVENT_BASELINE, MULTIFACTOR_SCORE
from src.kline.providers.catalyst_provider import CatalystEventProvider
from src.kline.ticker_resolver import TickerResolver
from src.kline.workspace_service import KlineWorkspaceService, filter_events_for_layer

kline_bp = Blueprint("kline", __name__)
workspace_service = KlineWorkspaceService()
catalyst_event_provider = CatalystEventProvider()
resolver = TickerResolver()

BACKTEST_STRATEGY_OPTIONS = (
    {"id": MULTIFACTOR_SCORE, "label": "Multifactor Score"},
    {"id": EVENT_BASELINE, "label": "Event Baseline"},
)
BACKTEST_PRICE_SOURCE_OPTIONS = (
    {"id": "tiingo", "label": "Research Snapshot"},
    {"id": "yfinance", "label": "Visible Chart Cache"},
)
SAFE_PARTITION_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")

__all__ = ["kline_bp"]


@kline_bp.get("/kline")
def kline_default():
    """Default K-line route with optional symbol query parameter."""
    symbol = (request.args.get("symbol") or "MRNA").strip().upper() or "MRNA"
    try:
        company = resolver.resolve(symbol)
    except ValueError as exc:
        return _invalid_ticker_response(str(exc))
    return redirect(url_for("kline.kline_view", symbol=company.ticker))


@kline_bp.get("/kline/<path:symbol>")
def kline_view(symbol: str):
    """Render the K-line workspace shell without blocking on data assembly."""
    try:
        company = resolver.resolve(symbol)
    except ValueError as exc:
        return _invalid_ticker_response(str(exc))
    return render_template(
        "kline_workspace.html",
        workspace=None,
        ticker=company.ticker,
        company=company.to_dict(),
        error=None,
        kline_active=True,
    )


@kline_bp.get("/api/kline/workspace/<symbol>")
def api_kline_workspace(symbol: str):
    """Return the serialized K-line workspace payload for a symbol."""
    refresh = _truthy_query_arg(request.args.get("refresh"))
    try:
        workspace = workspace_service.build_workspace(
            symbol,
            cache_only=not refresh,
        )
        return jsonify(workspace.to_dict())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@kline_bp.get("/api/kline/tickers")
def api_kline_tickers():
    """Return the resolver universe for K-line ticker selection."""
    return jsonify([company.to_dict() for company in resolver.list_universe()])


@kline_bp.get("/api/kline/events/<symbol>")
def api_kline_events(symbol: str):
    """Return Phase 2 event points for a symbol."""
    try:
        company = resolver.resolve(symbol)
        events, _statuses = catalyst_event_provider.load(company.ticker, cache_only=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    events = filter_events_for_layer(events, request.args.get("layer"))
    return jsonify([event.to_dict() for event in events])


@kline_bp.get("/api/kline/range-context/<symbol>")
def api_kline_range_context(symbol: str):
    """Return price and catalyst context for a selected K-line date range."""
    start_date = str(request.args.get("start") or "").strip()
    end_date = str(request.args.get("end") or "").strip()
    if not start_date or not end_date:
        return jsonify({"error": "start and end query parameters are required"}), 400
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "start and end must be in YYYY-MM-DD format"}), 400
    if start_dt > end_dt:
        return jsonify({"error": "invalid date range: start must be <= end"}), 400
    try:
        context = workspace_service.build_range_context(symbol, start_date, end_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(context.to_dict())


def _list_recent_data_snapshots(limit: int = 10) -> list[dict[str, str | None]]:
    try:
        safe_limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        safe_limit = 10

    path = initialize_research_database(RESEARCH_DB_PATH)
    import duckdb

    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT
                CAST(data_snapshot_id AS VARCHAR),
                CAST(snapshot_date AS VARCHAR),
                CAST(price_source AS VARCHAR),
                CAST(universe_id AS VARCHAR),
                CAST(bias_profile AS VARCHAR),
                CAST(created_at AS VARCHAR)
            FROM data_snapshots
            ORDER BY snapshot_date DESC NULLS LAST, created_at DESC NULLS LAST
            LIMIT ?
            """,
            [safe_limit],
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "data_snapshot_id": row[0],
            "snapshot_date": row[1],
            "price_source": row[2],
            "universe_id": row[3],
            "bias_profile": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]


def _snapshot_has_ticker_coverage(ticker: str, snapshot: dict[str, str | None]) -> bool:
    snapshot_id = str(snapshot.get("data_snapshot_id") or "").strip()
    source = str(snapshot.get("price_source") or "").strip()
    if (
        not snapshot_id
        or not SAFE_PARTITION_TOKEN.fullmatch(snapshot_id)
        or source not in {"tiingo", "yfinance"}
    ):
        return False

    source_root = (
        RESEARCH_DIR
        / "prices_daily"
        / f"data_snapshot_id={snapshot_id}"
        / f"source={source}"
    )
    if not source_root.exists():
        return False

    for path in sorted(source_root.glob("year=*/*.parquet")):
        if path.stem.upper() == ticker:
            return True
        try:
            tickers = pd.read_parquet(path, columns=["ticker"])["ticker"]
        except Exception:  # noqa: BLE001
            continue
        if ticker in set(tickers.astype(str).str.upper()):
            return True
    return False


def _select_default_data_snapshot(
    snapshots: list[dict[str, str | None]],
    ticker: str | None,
) -> dict[str, str | None] | None:
    normalized_ticker = normalize_kline_ticker(ticker) if ticker else None
    if normalized_ticker is not None:
        for snapshot in snapshots:
            if _snapshot_has_ticker_coverage(normalized_ticker, snapshot):
                return snapshot

    return snapshots[0] if snapshots else None


def _select_default_portfolio_snapshot(
    snapshots: list[dict[str, str | None]],
    universe_id: str = "biotech_us_v1",
) -> dict[str, str | None] | None:
    for snapshot in snapshots:
        if (
            snapshot.get("price_source") == "tiingo"
            and snapshot.get("universe_id") == universe_id
        ):
            return snapshot
    for snapshot in snapshots:
        if snapshot.get("price_source") == "tiingo":
            return snapshot
    return None


@kline_bp.get("/api/backtest/options")
def api_backtest_options():
    """Return real backtest strategy and data snapshot controls for K-line UI."""
    snapshots = _list_recent_data_snapshots()
    default_snapshot = _select_default_data_snapshot(
        snapshots,
        str(request.args.get("ticker") or "").strip(),
    )
    default_price_source = (
        default_snapshot.get("price_source")
        if default_snapshot and default_snapshot.get("price_source")
        else "yfinance"
    )
    if default_price_source not in {"tiingo", "yfinance"}:
        default_price_source = "tiingo"
    portfolio_snapshot = _select_default_portfolio_snapshot(snapshots)

    return jsonify(
        {
            "strategies": list(BACKTEST_STRATEGY_OPTIONS),
            "default_strategy_id": MULTIFACTOR_SCORE,
            "data_mode": "real",
            "backtest_mode": "exploratory",
            "price_sources": list(BACKTEST_PRICE_SOURCE_OPTIONS),
            "default_price_source": default_price_source,
            "default_data_snapshot_id": (
                default_snapshot.get("data_snapshot_id") if default_snapshot else None
            ),
            "portfolio": {
                "required_price_source": "tiingo",
                "default_price_source": "tiingo",
                "default_data_snapshot_id": (
                    portfolio_snapshot.get("data_snapshot_id")
                    if portfolio_snapshot
                    else None
                ),
                "universe_id": "biotech_us_v1",
            },
            "snapshots": snapshots,
        }
    )


def _parse_backtest_run_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (
            jsonify(
                {
                    "error": "request body must be a JSON object",
                }
            ),
            400,
        )

    raw_ticker = data.get("ticker")
    ticker = normalize_kline_ticker(raw_ticker)
    start_date = str(data.get("start_date") or "").strip()
    end_date = str(data.get("end_date") or "").strip()
    raw_strategy_id = data.get("strategy_id")
    strategy_id = str(raw_strategy_id).strip() if raw_strategy_id is not None else None
    if not strategy_id:
        strategy_id = None
    raw_data_mode = data.get("data_mode")
    data_mode = str(raw_data_mode).strip() if raw_data_mode is not None else None
    if not data_mode:
        data_mode = None
    raw_backtest_mode = data.get("backtest_mode")
    backtest_mode = (
        str(raw_backtest_mode).strip()
        if raw_backtest_mode is not None
        else "exploratory"
    )
    if not backtest_mode:
        backtest_mode = "exploratory"
    raw_price_source = data.get("price_source")
    price_source = str(raw_price_source).strip() if raw_price_source is not None else None
    if not price_source:
        price_source = None
    raw_data_snapshot_id = data.get("data_snapshot_id")
    data_snapshot_id = (
        str(raw_data_snapshot_id).strip()
        if raw_data_snapshot_id is not None
        else None
    )
    if not data_snapshot_id:
        data_snapshot_id = None
    raw_universe_id = data.get("universe_id")
    universe_id = (
        str(raw_universe_id).strip() if raw_universe_id is not None else "biotech_us_v1"
    )
    if not universe_id:
        universe_id = "biotech_us_v1"
    raw_strategy_config = data.get("strategy_config")
    strategy_config = None
    if raw_strategy_config is not None:
        try:
            strategy_config = normalize_real_multifactor_strategy_config(
                raw_strategy_config
            )
        except StrategyConfigError as exc:
            return None, (
                jsonify({"error": str(exc)}),
                400,
            )
    raw_persist_result = data.get("persist_result", True)
    if isinstance(raw_persist_result, bool):
        persist_result = raw_persist_result
    elif isinstance(raw_persist_result, str) and raw_persist_result.lower() in {
        "true",
        "false",
    }:
        persist_result = raw_persist_result.lower() == "true"
    else:
        return None, (
            jsonify({"error": "persist_result must be a boolean"}),
            400,
        )

    if not str(raw_ticker or "").strip() or not start_date or not end_date:
        return None, (
            jsonify(
                {
                    "error": "ticker, start_date, and end_date are required",
                }
            ),
            400,
        )

    if ticker is None:
        return None, (
            jsonify(
                {
                    "error": "invalid ticker: use 1-16 letters, numbers, dots, or hyphens",
                }
            ),
            400,
        )

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return None, (
            jsonify(
                {
                    "error": "start_date and end_date must be in YYYY-MM-DD format",
                }
            ),
            400,
        )

    if start_dt > end_dt:
        return None, (
            jsonify(
                {
                    "error": "invalid date range: start_date must be <= end_date",
                }
            ),
            400,
        )

    try:
        stop_loss_pct = float(data.get("stop_loss_pct", -0.08))
        max_position_pct = float(data.get("max_position_pct", 0.2))
        slippage_pct = float(data.get("slippage_pct", 0.001))
    except (TypeError, ValueError):
        return None, (
            jsonify(
                {
                    "error": "risk parameters must be numeric",
                }
            ),
            400,
        )

    risk_values = (stop_loss_pct, max_position_pct, slippage_pct)
    if not all(math.isfinite(value) for value in risk_values):
        return None, (
            jsonify(
                {
                    "error": "risk parameters must be finite numbers",
                }
            ),
            400,
        )

    if not (-1.0 < stop_loss_pct < 0):
        return None, (
            jsonify(
                {
                    "error": "stop_loss_pct must be greater than -1 and less than 0",
                }
            ),
            400,
        )

    if not (0 < max_position_pct <= 1):
        return None, (
            jsonify(
                {
                    "error": "max_position_pct must be greater than 0 and less than or equal to 1",
                }
            ),
            400,
        )

    if not (0 <= slippage_pct <= 0.2):
        return None, (
            jsonify(
                {
                    "error": "slippage_pct must be between 0 and 0.2",
                }
            ),
            400,
        )

    raw_holding_period = data.get("holding_period_days")
    holding_period_days = None
    if raw_holding_period not in (None, ""):
        try:
            holding_period_days = int(raw_holding_period)
        except (TypeError, ValueError):
            return None, (
                jsonify(
                    {
                        "error": "holding_period_days must be an integer between 1 and 60",
                    }
                ),
                400,
            )
        if not (1 <= holding_period_days <= 60):
            return None, (
                jsonify(
                    {
                        "error": "holding_period_days must be an integer between 1 and 60",
                    }
                ),
                400,
            )

    return {
        "data": data,
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "stop_loss_pct": stop_loss_pct,
        "max_position_pct": max_position_pct,
        "slippage_pct": slippage_pct,
        "holding_period_days": holding_period_days,
        "strategy_id": strategy_id,
        "data_mode": data_mode,
        "backtest_mode": backtest_mode,
        "price_source": price_source,
        "data_snapshot_id": data_snapshot_id,
        "universe_id": universe_id,
        "strategy_config": strategy_config,
        "persist_result": persist_result,
    }, None


@kline_bp.post("/api/backtest/run")
def api_backtest_run():
    """Run a single ticker backtest for K-line workflow."""
    parsed, error_response = _parse_backtest_run_request()
    if error_response is not None:
        return error_response

    assert parsed is not None

    result = run_kline_backtest(
        ticker=parsed["ticker"],
        start_date=parsed["start_date"],
        end_date=parsed["end_date"],
        stop_loss_pct=parsed["stop_loss_pct"],
        max_position_pct=parsed["max_position_pct"],
        slippage_pct=parsed["slippage_pct"],
        holding_period_days=parsed["holding_period_days"],
        strategy_id=parsed["strategy_id"],
        data_mode=parsed["data_mode"],
        backtest_mode=parsed["backtest_mode"],
        price_source=parsed["price_source"],
        data_snapshot_id=parsed["data_snapshot_id"],
        strategy_config=parsed["strategy_config"],
        persist_result=parsed["persist_result"],
    )

    if isinstance(result, dict) and result.get("error"):
        return jsonify({"error": result.get("error")}), 400

    return jsonify(result)


@kline_bp.post("/api/backtest/portfolio/run")
def api_backtest_portfolio_run():
    """Run the real biotech universe backtest for the K-line workflow."""
    parsed, error_response = _parse_backtest_run_request()
    if error_response is not None:
        return error_response

    assert parsed is not None
    if not parsed["data_snapshot_id"]:
        return jsonify({"error": "data_snapshot_id is required for portfolio backtests"}), 400

    portfolio_price_source = parsed["price_source"] or "tiingo"
    if portfolio_price_source != "tiingo":
        return jsonify({"error": "portfolio backtests require tiingo snapshot prices"}), 400

    result = run_real_biotech_portfolio_backtest(
        focus_ticker=parsed["ticker"],
        start_date=parsed["start_date"],
        end_date=parsed["end_date"],
        stop_loss_pct=parsed["stop_loss_pct"],
        max_position_pct=parsed["max_position_pct"],
        slippage_pct=parsed["slippage_pct"],
        holding_period_days=parsed["holding_period_days"],
        universe_id=parsed["universe_id"],
        strategy_id=parsed["strategy_id"],
        as_of_date=None if parsed["data_snapshot_id"] else parsed["end_date"],
        data_snapshot_id=parsed["data_snapshot_id"],
        price_source=portfolio_price_source,
        strategy_config=parsed["strategy_config"],
        persist_result=parsed["persist_result"],
    )

    if isinstance(result, dict) and result.get("error"):
        return jsonify(result), 400

    return jsonify(result)


@kline_bp.get("/api/backtest/results/<run_id>")
def api_backtest_result(run_id: str):
    """Load a saved backtest run by run_id."""
    payload = load_saved_run(run_id)
    if payload is None:
        return jsonify({"error": "backtest run not found"}), 404
    return jsonify(payload)


def _invalid_ticker_response(message: str):
    return (
        render_template(
            "kline_workspace.html",
            workspace=None,
            error=message,
            kline_active=True,
        ),
        400,
    )


def _truthy_query_arg(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "refresh"}
