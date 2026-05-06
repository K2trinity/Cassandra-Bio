# src/backtest/signals.py
"""Signal generation: event score × report confidence → trade signal."""

import math

import pandas as pd
import numpy as np

from src.kline.event_filter import decode_metadata

EVENT_SCORE = {
    "fda_decision": 1.0,
    "fda_approval": 1.0,
    "fda_label_update": 0.7,
    "fda_recall": 0.8,
    "clinical_readout": 0.9,
    "trial_results_posted": 0.95,
    "trial_primary_completion": 0.7,
    "trial_completion": 0.55,
    "trial_status_change": 0.45,
    "trial_termination": 0.9,
    "safety_signal": 0.75,
    "partnership": 0.6,
    "partnership_mna": 0.65,
    "financing": 0.4,
    "earnings_financing": 0.45,
    "patent": 0.3,
    "competitor": 0.5,
    "market_news": 0.4,
    "analyst_news": 0.35,
    "geopolitical": 0.3,
    "trade_policy": 0.3,
    "sanctions": 0.4,
    "regulatory_change": 0.4,
    "macro_policy": 0.3,
    "macro_economic": 0.2,
}

PRIORITY_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.3, 4: 0.2, 5: 0.15}

SENTIMENT_DIRECTION = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def align_events_to_trading_dates(
    events_df: pd.DataFrame, ohlc_df: pd.DataFrame
) -> pd.DataFrame:
    """Map event dates to the next available trading date in the OHLC window."""
    if events_df.empty or ohlc_df.empty:
        return events_df.copy()
    if "date" not in events_df.columns or "date" not in ohlc_df.columns:
        return events_df.copy()

    events = events_df.copy()
    ohlc_dates = _normalize_dates(ohlc_df["date"]).dropna()
    if ohlc_dates.empty:
        return events

    trading_dates = pd.Series(ohlc_dates.unique()).sort_values()
    event_dates = _normalize_dates(events["date"])
    positions = trading_dates.searchsorted(event_dates, side="left")
    valid_mask = event_dates.notna() & (positions < len(trading_dates))

    events = events.loc[valid_mask].copy()
    if events.empty:
        return events.reset_index(drop=True)

    valid_positions = positions[valid_mask.to_numpy()]
    if "original_event_date" not in events.columns:
        events["original_event_date"] = event_dates[valid_mask].to_numpy()
    events["date"] = trading_dates.iloc[valid_positions].to_numpy()
    return events.reset_index(drop=True)


def _normalize_dates(values: pd.Series) -> pd.Series:
    dates = values.apply(_normalize_date_value)
    return pd.to_datetime(dates, errors="coerce").astype("datetime64[ns]")


def _normalize_date_value(value: object) -> pd.Timestamp:
    try:
        date = pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(date):
        return pd.NaT
    if date.tzinfo is not None:
        date = date.tz_localize(None)
    return date.normalize()


def score_event(event: dict) -> float:
    """Score a single event using phase2 metadata when available."""
    metadata = decode_metadata(event.get("metadata"))
    if "backtest_eligible" in metadata and not _bool_value(
        metadata.get("backtest_eligible")
    ):
        return 0.0

    impact_score = _float_value(metadata.get("impact_score"))
    confidence_score = _float_value(metadata.get("confidence_score"))
    type_w = (
        impact_score
        if impact_score is not None
        else EVENT_SCORE.get(event.get("type", ""), 0.3)
    )
    prio_w = PRIORITY_WEIGHT.get(_int_value(event.get("priority", 3), 3), 0.3)
    sent_d = SENTIMENT_DIRECTION.get(event.get("sentiment", "neutral"), 0.0)
    confidence_w = confidence_score if confidence_score is not None else 1.0
    return round(type_w * prio_w * sent_d * confidence_w, 6)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _float_value(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def generate_signals(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    report_confidence: float = 0.5,
) -> pd.DataFrame:
    """Generate daily trade signals from events + optional report confidence.

    Args:
        ohlc_df: OHLC with 'date' column.
        events_df: Events with 'date', 'type', 'priority', 'sentiment'.
        report_confidence: Cassandra report confidence multiplier [0, 1].

    Returns:
        DataFrame with columns [date, signal, signal_strength].
        signal: 1 (long), -1 (short), 0 (no signal).
    """
    df = ohlc_df[["date"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["raw_score"] = 0.0

    if not events_df.empty:
        ev = events_df.copy()
        ev["date"] = pd.to_datetime(ev["date"])
        ev["score"] = ev.apply(score_event, axis=1)

        daily_score = ev.groupby("date")["score"].sum().reset_index()
        daily_score.columns = ["date", "event_score"]

        df = df.merge(daily_score, on="date", how="left")
        df["event_score"] = df["event_score"].fillna(0)
        df["raw_score"] = df["event_score"] * report_confidence

    # Signal: threshold-based
    df["signal"] = 0
    df.loc[df["raw_score"] > 0.15, "signal"] = 1
    df.loc[df["raw_score"] < -0.15, "signal"] = -1
    df["signal_strength"] = df["raw_score"].abs()

    return df[["date", "signal", "signal_strength"]]
