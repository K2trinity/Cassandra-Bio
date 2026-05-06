"""Flask routes for the K-line workspace and backtest APIs."""

from __future__ import annotations

import math
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from src.backtest.runner import (
    load_saved_run,
    normalize_kline_ticker,
    run_kline_backtest,
)
from src.kline.ticker_resolver import TickerResolver
from src.kline.workspace_service import KlineWorkspaceService

kline_bp = Blueprint("kline", __name__)
workspace_service = KlineWorkspaceService()
resolver = TickerResolver()

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
    """Render the K-line phase 1 workspace."""
    try:
        workspace = workspace_service.build_workspace(symbol)
    except ValueError as exc:
        return _invalid_ticker_response(str(exc))
    return render_template(
        "kline_workspace.html",
        workspace=workspace.to_dict(),
        error=None,
        kline_active=True,
    )


@kline_bp.get("/api/kline/workspace/<symbol>")
def api_kline_workspace(symbol: str):
    """Return the serialized K-line workspace payload for a symbol."""
    try:
        return jsonify(workspace_service.build_workspace(symbol).to_dict())
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
        workspace = workspace_service.build_workspace(symbol)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    event_layer_kinds = {"catalysts", "news", "macro"}
    events = [
        event
        for layer in workspace.layers
        if layer.kind in event_layer_kinds
        for event in layer.points
    ]
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


@kline_bp.post("/api/backtest/run")
def api_backtest_run():
    """Run a single ticker backtest for K-line workflow."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return (
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
    strategy_id = str(raw_strategy_id).strip() if raw_strategy_id else None
    raw_data_mode = data.get("data_mode")
    data_mode = str(raw_data_mode).strip() if raw_data_mode else None

    if not str(raw_ticker or "").strip() or not start_date or not end_date:
        return (
            jsonify(
                {
                    "error": "ticker, start_date, and end_date are required",
                }
            ),
            400,
        )

    if ticker is None:
        return (
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
        return (
            jsonify(
                {
                    "error": "start_date and end_date must be in YYYY-MM-DD format",
                }
            ),
            400,
        )

    if start_dt > end_dt:
        return (
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
        return (
            jsonify(
                {
                    "error": "risk parameters must be numeric",
                }
            ),
            400,
        )

    risk_values = (stop_loss_pct, max_position_pct, slippage_pct)
    if not all(math.isfinite(value) for value in risk_values):
        return (
            jsonify(
                {
                    "error": "risk parameters must be finite numbers",
                }
            ),
            400,
        )

    if not (-1.0 < stop_loss_pct < 0):
        return (
            jsonify(
                {
                    "error": "stop_loss_pct must be greater than -1 and less than 0",
                }
            ),
            400,
        )

    if not (0 < max_position_pct <= 1):
        return (
            jsonify(
                {
                    "error": "max_position_pct must be greater than 0 and less than or equal to 1",
                }
            ),
            400,
        )

    if not (0 <= slippage_pct <= 0.2):
        return (
            jsonify(
                {
                    "error": "slippage_pct must be between 0 and 0.2",
                }
            ),
            400,
        )

    result = run_kline_backtest(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        slippage_pct=slippage_pct,
        strategy_id=strategy_id,
        data_mode=data_mode,
    )

    if isinstance(result, dict) and result.get("error"):
        return jsonify({"error": result.get("error")}), 400

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
