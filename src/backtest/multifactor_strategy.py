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
DEFAULT_MOCK_SIGNAL_THRESHOLD = 0.15


def generate_mock_multifactor_signals(
    price_window: pd.DataFrame,
    factors: pd.DataFrame,
    threshold: float = DEFAULT_MOCK_SIGNAL_THRESHOLD,
) -> pd.DataFrame:
    signals = price_window[["date"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    signals = signals.merge(
        _factor_scores(factors),
        on="date",
        how="left",
        validate="many_to_one",
    )
    signals["mock_score"] = signals["mock_score"].fillna(0.0)
    signals["signal"] = 0
    active = signals["mock_score"] > threshold
    signals.loc[active, "signal"] = 1
    signals["signal_strength"] = 0.0
    signals.loc[active, "signal_strength"] = signals.loc[
        active, "mock_score"
    ].clip(upper=1.0)
    return signals[["date", "signal", "signal_strength"]]


def summarize_factor_attribution(
    factors: pd.DataFrame,
    threshold: float = DEFAULT_MOCK_SIGNAL_THRESHOLD,
) -> dict[str, Any]:
    rows = _coerce_factor_frame(factors)
    if rows.empty:
        return _empty_factor_attribution()

    active = rows[rows["mock_score"] > threshold]
    if active.empty:
        return _empty_factor_attribution()

    summary = {
        "active_factor_days": int(len(active)),
        "mean_mock_score": _round_float(active["mock_score"].mean()),
    }
    for column in FACTOR_COLUMNS:
        summary[f"mean_{column}"] = _round_float(active[column].mean())
    return summary


def _factor_scores(factors: pd.DataFrame) -> pd.DataFrame:
    if factors.empty or "date" not in factors.columns:
        return pd.DataFrame(columns=["date", "mock_score"])
    rows = _coerce_factor_frame(factors)
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows = rows.dropna(subset=["date"])
    if rows.empty:
        return pd.DataFrame(columns=["date", "mock_score"])
    return rows.groupby("date", as_index=False, sort=True)["mock_score"].max()


def _coerce_factor_frame(factors: pd.DataFrame) -> pd.DataFrame:
    rows = factors.copy()
    for column in ["mock_score", *FACTOR_COLUMNS]:
        if column not in rows.columns:
            rows[column] = 0.0
        numeric = pd.to_numeric(rows[column], errors="coerce")
        rows[column] = numeric.replace([math.inf, -math.inf], 0.0).fillna(0.0)
    return rows


def _empty_factor_attribution() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "active_factor_days": 0,
        "mean_mock_score": 0.0,
    }
    for column in FACTOR_COLUMNS:
        summary[f"mean_{column}"] = 0.0
    return summary


def _round_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)
