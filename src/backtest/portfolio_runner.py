"""Portfolio-level K-line backtest aggregation for the biotech K-line universe."""

from __future__ import annotations

from datetime import datetime
import uuid

from src.backtest.runner import normalize_kline_ticker, run_kline_backtest

BIOTECH_REAL_UNIVERSE_ID = "biotech_four_v1"
BIOTECH_MOCK_UNIVERSE_ID = "biotech_mock_v1"
BIOTECH_REAL_TICKERS = ("MRNA", "JNJ", "LLY", "XBI")
BIOTECH_MOCK_TICKERS = ("MRNA", "JNJ", "LLY", "ABBA")
REAL_MULTIFACTOR_STRATEGY_ID = "multifactor_score"
MOCK_MULTIFACTOR_STRATEGY_ID = "mock_multifactor_demo"
DISCLOSURE_KEYS = {
    "mock_metadata",
    "synthetic",
    "data_mode",
    "positive_demo_expected",
    "mock",
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


def _run_biotech_portfolio_backtest(
    focus_ticker: str,
    start_date: str,
    end_date: str,
    *,
    universe_id: str,
    tickers: tuple[str, ...],
    strategy_id: str,
    data_mode: str,
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
        )
        if isinstance(payload, dict) and payload.get("error"):
            return {"error": f"{ticker}: {payload.get('error')}"}
        runs.append(payload)

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
        "tickers": list(tickers),
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
) -> dict:
    """Run the real multifactor strategy across the four-ticker biotech universe."""
    return _run_biotech_portfolio_backtest(
        focus_ticker=focus_ticker,
        start_date=start_date,
        end_date=end_date,
        universe_id=BIOTECH_REAL_UNIVERSE_ID,
        tickers=BIOTECH_REAL_TICKERS,
        strategy_id=REAL_MULTIFACTOR_STRATEGY_ID,
        data_mode="real",
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        slippage_pct=slippage_pct,
        holding_period_days=holding_period_days,
    )


def run_mock_biotech_portfolio_backtest(
    focus_ticker: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    holding_period_days: int | None = None,
) -> dict:
    """Run and aggregate the guarded mock strategy across the biotech demo universe."""
    return _run_biotech_portfolio_backtest(
        focus_ticker=focus_ticker,
        start_date=start_date,
        end_date=end_date,
        universe_id=BIOTECH_MOCK_UNIVERSE_ID,
        tickers=BIOTECH_MOCK_TICKERS,
        strategy_id=MOCK_MULTIFACTOR_STRATEGY_ID,
        data_mode="mock",
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        slippage_pct=slippage_pct,
        holding_period_days=holding_period_days,
    )
