from __future__ import annotations

import pytest


@pytest.fixture
def use_temp_db(monkeypatch, tmp_path):
    from src.backtest import events_db

    monkeypatch.setattr(events_db, "DB_PATH", tmp_path / "events.db")
    events_db.init_db()
    events_db.init_fetch_log_table()
    return events_db


def _stub_empty_non_trial_sources(monkeypatch):
    from src.services import event_ingestion_service

    class EmptyFDA:
        def collect(self, ticker, limit=20):
            return {
                "label": {"results": []},
                "event": {"results": []},
                "drugsfda": {"results": []},
            }

    monkeypatch.setattr(
        event_ingestion_service,
        "OpenFDAClient",
        lambda *args, **kwargs: EmptyFDA(),
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_market_news_events",
        lambda ticker: ([], {"status": "disabled", "message": "no key"}),
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_biotech_macro_events",
        lambda *args, **kwargs: [],
    )


def _trial(**overrides):
    trial = {
        "nct_id": "NCT00000001",
        "title": "Phase 2 RNA biomarker study",
        "status": "COMPLETED",
        "sponsor": "ModernaTX, Inc.",
        "conditions": "Oncology",
        "interventions": "RNA biomarker assay",
        "phase": "Phase 2",
        "has_results": True,
        "primary_completion_date": "2026-04-18",
        "completion_date": "2026-04-19",
        "last_update_posted": "2026-04-20",
    }
    trial.update(overrides)
    return trial


def test_ingestion_returns_only_trusted_events(monkeypatch, use_temp_db):
    from src.services import event_ingestion_service

    use_temp_db.insert_event(
        {
            "id": "legacy-mrna",
            "date": "2026-04-20",
            "type": "clinical_readout",
            "priority": 2,
            "ticker": "MRNA",
            "disease_area": "Oncology",
            "catalyst": "Legacy Clinical Trial: Phase 2 readout",
            "sentiment": "neutral",
            "price_impact": None,
            "source": "clinicaltrials",
            "source_ids": [],
            "metadata": {},
        }
    )
    _stub_empty_non_trial_sources(monkeypatch)
    monkeypatch.setattr(
        event_ingestion_service,
        "search_trials",
        lambda *args, **kwargs: [],
    )

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events == []
    statuses = {
        row["source"]: row["status"]
        for row in event_ingestion_service.get_source_statuses_for_ticker("MRNA")
    }
    assert statuses["clinicaltrials"] == "empty"
    assert statuses["alphavantage"] == "disabled"


def test_unowned_clinical_trial_is_quarantined_not_returned(monkeypatch, use_temp_db):
    from src.services import event_ingestion_service

    _stub_empty_non_trial_sources(monkeypatch)
    monkeypatch.setattr(
        event_ingestion_service,
        "search_trials",
        lambda *args, **kwargs: [
            _trial(
                sponsor="University Research Center",
                title="Phase 2 RNA biomarker study",
            )
        ],
    )

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events == []
    rows = use_temp_db.get_events("MRNA")
    assert set(rows["trust_status"]) == {"quarantined"}
    assert set(rows["ownership_status"]) == {"unowned"}


def test_owned_clinical_trial_becomes_trusted(monkeypatch, use_temp_db):
    from src.services import event_ingestion_service

    _stub_empty_non_trial_sources(monkeypatch)
    monkeypatch.setattr(
        event_ingestion_service,
        "search_trials",
        lambda *args, **kwargs: [
            _trial(
                sponsor="ModernaTX, Inc.",
                title="Phase 2 owned RNA biomarker study",
            )
        ],
    )

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events
    assert {event["ticker_scope"] for event in events} == {"MRNA"}
    assert {event["trust_status"] for event in events} == {"trusted"}
    assert {event["ownership_status"] for event in events} == {"owned"}
