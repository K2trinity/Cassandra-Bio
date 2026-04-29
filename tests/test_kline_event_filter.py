from __future__ import annotations

import pandas as pd


def test_score_event_metadata_marks_official_clinical_event_backtest_eligible():
    from src.kline.event_filter import enrich_event_metadata

    event = enrich_event_metadata(
        {
            "ticker": "MRNA",
            "date": "2026-04-20",
            "type": "trial_results_posted",
            "source": "clinicaltrials",
            "priority": 1,
            "sentiment": "positive",
            "source_ids": ["NCT00000001"],
            "metadata": {},
        }
    )

    assert event["category"] == "clinical"
    assert event["metadata"]["category"] == "clinical"
    assert event["metadata"]["source_kind"] == "clinical"
    assert event["metadata"]["source_tier"] == "official"
    assert event["metadata"]["confidence_score"] >= 0.7
    assert event["metadata"]["impact_score"] >= 0.5
    assert event["metadata"]["backtest_eligible"] is True
    assert event["metadata"]["dedupe_key"] == (
        "MRNA|clinicaltrials|trial_results_posted|NCT00000001|2026-04-20"
    )


def test_macro_event_is_visible_but_not_backtest_eligible_by_default():
    from src.kline.event_filter import enrich_event_metadata

    event = enrich_event_metadata(
        {
            "ticker": "MRNA",
            "date": "2026-04-20",
            "type": "macro_economic",
            "source": "gdelt",
            "priority": 3,
            "sentiment": "neutral",
            "source_url": "https://example.com/macro",
            "metadata": {},
        }
    )

    assert event["category"] == "macro"
    assert event["metadata"]["source_kind"] == "macro"
    assert event["metadata"]["source_tier"] == "macro"
    assert event["metadata"]["confidence_score"] < 0.85
    assert event["metadata"]["backtest_eligible"] is False


def test_filter_backtest_events_returns_summary_and_only_eligible_rows():
    from src.kline.event_filter import filter_backtest_events

    rows = pd.DataFrame(
        [
            {
                "id": "eligible",
                "date": "2026-04-20",
                "type": "trial_results_posted",
                "source": "clinicaltrials",
                "metadata": '{"backtest_eligible": true, "confidence_score": 0.9}',
            },
            {
                "id": "excluded",
                "date": "2026-04-21",
                "type": "macro_economic",
                "source": "gdelt",
                "metadata": '{"backtest_eligible": false, "confidence_score": 0.4}',
            },
        ]
    )

    eligible, summary = filter_backtest_events(rows)

    assert eligible["id"].tolist() == ["eligible"]
    assert summary == {
        "input_events": 2,
        "eligible_events": 1,
        "excluded_events": 1,
        "min_confidence_score": 0.7,
    }


def test_filter_backtest_events_enriches_legacy_rows_before_filtering():
    from src.kline.event_filter import filter_backtest_events

    rows = pd.DataFrame(
        [
            {
                "id": "official-regulatory",
                "date": "2026-04-20",
                "type": "fda_label_update",
                "source": "openfda",
                "ticker": "MRNA",
                "priority": 2,
                "sentiment": "positive",
                "source_ids": ["FDA-123"],
                "metadata": "{}",
            },
            {
                "id": "macro-visual",
                "date": "2026-04-21",
                "type": "macro_economic",
                "source": "gdelt",
                "ticker": "MRNA",
                "priority": 3,
                "sentiment": "neutral",
                "metadata": "{}",
            },
        ]
    )

    eligible, summary = filter_backtest_events(rows)

    assert eligible["id"].tolist() == ["official-regulatory"]
    assert eligible.iloc[0]["metadata"]["source_tier"] == "official"
    assert eligible.iloc[0]["metadata"]["backtest_eligible"] is True
    assert summary == {
        "input_events": 2,
        "eligible_events": 1,
        "excluded_events": 1,
        "min_confidence_score": 0.7,
    }
