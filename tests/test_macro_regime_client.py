from __future__ import annotations

import pandas as pd

from src.tools.macro_regime_client import build_macro_regime_events


def frame(closes):
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "date": pd.Timestamp("2026-04-20") + pd.Timedelta(days=index),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_builds_sector_underperformance_event_from_xbi_vs_spy():
    events = build_macro_regime_events(
        "MRNA",
        {
            "XBI": frame([100, 98, 96, 93, 90]),
            "SPY": frame([100, 101, 102, 103, 104]),
        },
    )

    assert len(events) == 1
    event = events[0]
    assert event["source"] == "macro_regime"
    assert event["type"] == "sector_underperformance"
    assert event["ticker"] == "MRNA"
    assert event["sentiment"] == "negative"
    assert event["metadata"]["benchmark"] == "XBI"
    assert event["metadata"]["backtest_eligible"] is True


def test_builds_vix_risk_off_event_when_vix_is_elevated():
    events = build_macro_regime_events(
        "MRNA",
        {
            "^VIX": frame([15, 18, 22, 27, 31]),
        },
    )

    assert [event["type"] for event in events] == ["macro_risk_off"]
    assert events[0]["priority"] == 2
