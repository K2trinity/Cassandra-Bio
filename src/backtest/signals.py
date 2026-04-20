# src/backtest/signals.py
"""Signal generation: event score × report confidence → trade signal."""

import pandas as pd
import numpy as np


EVENT_SCORE = {
    "fda_decision": 1.0,
    "clinical_readout": 0.9,
    "partnership": 0.6,
    "financing": 0.4,
    "patent": 0.3,
    "competitor": 0.5,
}

PRIORITY_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.3}

SENTIMENT_DIRECTION = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def score_event(event: dict) -> float:
    """Score a single event: type_weight × priority_weight × sentiment_direction."""
    type_w = EVENT_SCORE.get(event.get("type", ""), 0.3)
    prio_w = PRIORITY_WEIGHT.get(event.get("priority", 3), 0.3)
    sent_d = SENTIMENT_DIRECTION.get(event.get("sentiment", "neutral"), 0.0)
    return type_w * prio_w * sent_d


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
