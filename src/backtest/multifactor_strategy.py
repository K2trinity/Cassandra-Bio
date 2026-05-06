from __future__ import annotations

import math
from typing import Any

import pandas as pd

FACTOR_COLUMNS = [
    "event_factor",
    "momentum_factor",
    "volume_shock",
    "volatility_penalty",
    "liquidity_factor",
    "regime_factor",
]


def generate_mock_multifactor_signals(
    price_window: pd.DataFrame,
    factors: pd.DataFrame,
    threshold: float = 0.15,
) -> pd.DataFrame:
    signals = price_window[["date"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    signals = signals.merge(_factor_scores(factors), on="date", how="left")
    signals["mock_score"] = signals["mock_score"].fillna(0.0)
    signals["signal"] = 0
    signals.loc[signals["mock_score"] > threshold, "signal"] = 1
    signals["signal_strength"] = signals["mock_score"].abs().clip(upper=1.0)
    return signals[["date", "signal", "signal_strength"]]


def summarize_factor_attribution(factors: pd.DataFrame) -> dict[str, Any]:
    if factors.empty or "mock_score" not in factors.columns:
        return {
            "active_factor_days": 0,
            "mean_mock_score": 0.0,
            "mean_event_factor": 0.0,
            "mean_momentum_factor": 0.0,
            "mean_volume_shock": 0.0,
            "mean_volatility_penalty": 0.0,
            "mean_liquidity_factor": 0.0,
            "mean_regime_factor": 0.0,
        }

    rows = factors.copy()
    active = rows[rows["mock_score"] > 0.15]
    if active.empty:
        return {
            "active_factor_days": 0,
            "mean_mock_score": 0.0,
            "mean_event_factor": 0.0,
            "mean_momentum_factor": 0.0,
            "mean_volume_shock": 0.0,
            "mean_volatility_penalty": 0.0,
            "mean_liquidity_factor": 0.0,
            "mean_regime_factor": 0.0,
        }

    return {
        "active_factor_days": int(len(active)),
        "mean_mock_score": _round_float(active["mock_score"].mean()),
        "mean_event_factor": _round_float(active["event_factor"].mean()),
        "mean_momentum_factor": _round_float(active["momentum_factor"].mean()),
        "mean_volume_shock": _round_float(active["volume_shock"].mean()),
        "mean_volatility_penalty": _round_float(active["volatility_penalty"].mean()),
        "mean_liquidity_factor": _round_float(active["liquidity_factor"].mean()),
        "mean_regime_factor": _round_float(active["regime_factor"].mean()),
    }


def _factor_scores(factors: pd.DataFrame) -> pd.DataFrame:
    if factors.empty:
        return pd.DataFrame(columns=["date", "mock_score"])
    rows = factors[["date", "mock_score"]].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    rows["mock_score"] = pd.to_numeric(rows["mock_score"], errors="coerce").fillna(0.0)
    return rows


def _round_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)
