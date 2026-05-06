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
    threshold = _validate_threshold(threshold)
    signals = price_window[["date"]].copy()
    signals["date"] = _normalize_dates(signals["date"])
    signals = signals.merge(
        _factor_scores(factors),
        on="date",
        how="left",
        validate="many_to_one",
    )
    signals["mock_score"] = signals["mock_score"].fillna(0.0)
    active = signals["mock_score"] > threshold
    signals["signal"] = active.astype(int)
    signals["signal_strength"] = signals["mock_score"].where(active, 0.0).clip(
        lower=0.0,
        upper=1.0,
    )
    return signals[["date", "signal", "signal_strength"]]


def summarize_factor_attribution(
    factors: pd.DataFrame,
    threshold: float = DEFAULT_MOCK_SIGNAL_THRESHOLD,
) -> dict[str, Any]:
    threshold = _validate_threshold(threshold)
    try:
        rows = _normalized_factor_rows(factors)
    except (AttributeError, KeyError, TypeError, ValueError):
        return _empty_factor_attribution()
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
    return _normalized_factor_rows(factors)[["date", "mock_score"]]


def _normalized_factor_rows(factors: pd.DataFrame) -> pd.DataFrame:
    if not factors.columns.is_unique:
        raise ValueError("factors must have unique columns")
    if factors.empty:
        return _empty_normalized_factor_rows()
    if "date" not in factors.columns:
        return _empty_normalized_factor_rows()

    rows = factors.copy()
    rows["date"] = _normalize_dates(rows["date"])
    for column in ["mock_score", *FACTOR_COLUMNS]:
        if column not in rows.columns:
            rows[column] = 0.0
        rows[column] = _coerce_numeric_series(rows[column])

    rows = rows.dropna(subset=["date"])
    if rows.empty:
        return _empty_normalized_factor_rows()

    rows = rows[["date", "mock_score", *FACTOR_COLUMNS]].reset_index(drop=True)
    rows["_source_order"] = range(len(rows))
    rows = rows.sort_values(
        ["date", "mock_score", "_source_order"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    rows = rows.drop_duplicates(subset=["date"], keep="first")
    return rows.drop(columns=["_source_order"]).reset_index(drop=True)


def _normalize_dates(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, utc=True, errors="coerce")
    return dates.dt.tz_convert(None).dt.normalize().astype("datetime64[ns]")


def _coerce_numeric_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.replace([math.inf, -math.inf], 0.0).fillna(0.0).astype(float)


def _empty_normalized_factor_rows() -> pd.DataFrame:
    rows = {
        "date": pd.Series(dtype="datetime64[ns]"),
        "mock_score": pd.Series(dtype="float64"),
    }
    for column in FACTOR_COLUMNS:
        rows[column] = pd.Series(dtype="float64")
    return pd.DataFrame(rows)


def _validate_threshold(threshold: float) -> float:
    try:
        number = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold must be non-negative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("threshold must be non-negative")
    return number


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
