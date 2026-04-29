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
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_macro_regime_events",
        lambda *args, **kwargs: [],
        raising=False,
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


def _single_milestone_trial(**overrides):
    return _trial(
        primary_completion_date=None,
        last_update_posted=None,
        **overrides,
    )


def _normalized_single_milestone_event(trial):
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [trial],
        source="clinicaltrials",
        requested_ticker="MRNA",
        include_unowned=True,
    )
    assert len(events) == 1
    return events[0]


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


def test_legacy_duplicate_clinical_trial_refresh_updates_trust_fields(
    monkeypatch,
    use_temp_db,
):
    from src.services import event_ingestion_service

    trial = _single_milestone_trial(completion_date="2026-04-19")
    normalized = _normalized_single_milestone_event(trial)
    legacy_event = dict(normalized)
    legacy_event["metadata"] = {}
    legacy_event["source_ids"] = []
    use_temp_db.insert_event(legacy_event)

    _stub_empty_non_trial_sources(monkeypatch)
    monkeypatch.setattr(
        event_ingestion_service,
        "search_trials",
        lambda *args, **kwargs: [trial],
    )

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert [event["id"] for event in events] == [normalized["id"]]
    rows = use_temp_db.get_events("MRNA")
    row = rows.loc[rows["id"] == normalized["id"]].iloc[0]
    assert row["trust_status"] == "trusted"
    assert row["ownership_status"] == "owned"
    assert row["schema_version"] == 2


def test_trusted_duplicate_clinical_trial_refresh_quarantines_lost_ownership(
    monkeypatch,
    use_temp_db,
):
    from src.kline.event_trust import apply_event_trust
    from src.services import event_ingestion_service

    owned_trial = _single_milestone_trial(completion_date="2026-04-19")
    unowned_trial = _single_milestone_trial(
        completion_date="2026-04-19",
        sponsor="University Research Center",
        collaborators="",
    )
    trusted_event = apply_event_trust(
        _normalized_single_milestone_event(owned_trial),
        ticker="MRNA",
        source="clinicaltrials",
        source_run_id="clinicaltrials:MRNA:20260420T000000Z:trusted",
        query_hash="trustedqueryhash",
        company_identity="MRNA|Moderna, Inc.",
        ownership_status="owned",
        trust_status="trusted",
    )
    use_temp_db.insert_event(trusted_event)

    _stub_empty_non_trial_sources(monkeypatch)
    monkeypatch.setattr(
        event_ingestion_service,
        "search_trials",
        lambda *args, **kwargs: [unowned_trial],
    )

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events == []
    rows = use_temp_db.get_events("MRNA")
    row = rows.loc[rows["id"] == trusted_event["id"]].iloc[0]
    assert row["trust_status"] == "quarantined"
    assert row["ownership_status"] == "unowned"
    assert (
        row["quarantine_reason"]
        == "clinical trial sponsor/collaborator did not match requested ticker"
    )


def test_clinical_event_without_ownership_status_metadata_is_quarantined():
    from src.services.event_ingestion_service import _ownership_for_event

    ownership_status, trust_status, quarantine_reason = _ownership_for_event(
        {
            "source": "clinicaltrials",
            "metadata": {"entity_match": "sponsor"},
        },
        "clinicaltrials",
    )

    assert ownership_status == "unknown"
    assert trust_status == "quarantined"
    assert quarantine_reason == "missing clinical ownership evidence"


def test_macro_regime_event_is_trusted_macro_context():
    from src.services.event_ingestion_service import _ownership_for_event

    ownership_status, trust_status, quarantine_reason = _ownership_for_event(
        {"source": "macro_regime"},
        "macro_regime",
    )

    assert ownership_status == "macro_context"
    assert trust_status == "trusted"
    assert quarantine_reason is None


@pytest.mark.parametrize("entity_match", [True, ["sponsor"], "bogus"])
def test_owned_clinical_event_with_invalid_entity_match_is_quarantined(entity_match):
    from src.services.event_ingestion_service import _ownership_for_event

    ownership_status, trust_status, quarantine_reason = _ownership_for_event(
        {
            "source": "clinicaltrials",
            "metadata": {
                "ownership_status": "owned",
                "entity_match": entity_match,
            },
        },
        "clinicaltrials",
    )

    assert ownership_status == "unknown"
    assert trust_status == "quarantined"
    assert quarantine_reason == "malformed clinical ownership evidence"
