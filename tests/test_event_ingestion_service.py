"""
Tests for biotech event normalization from openFDA and ClinicalTrials.

These tests verify that raw API payloads are correctly normalized into
a consistent biotech_events schema for downstream analysis.
"""

import pytest
from datetime import datetime
from typing import Dict, Any

# ========== Test Fixtures ==========


@pytest.fixture(autouse=True)
def isolated_events_db(tmp_path, monkeypatch):
    """Keep DB-touching tests away from the repo's persistent event store."""
    from src.backtest import events_db
    from src.services import event_ingestion_service

    monkeypatch.setattr(events_db, "DB_PATH", tmp_path / "events.db")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_macro_regime_events",
        lambda *args, **kwargs: [],
        raising=False,
    )


@pytest.fixture
def openfda_approval_payload() -> Dict[str, Any]:
    """Realistic openFDA approval payload."""
    return {
        "results": [
            {
                "application_number": "BLA125514",
                "sponsor_name": "Moderna Inc",
                "openfda": {
                    "brand_name": ["SPIKEVAX"],
                    "generic_name": ["mRNA-1273"],
                },
                "products": [
                    {
                        "brand_name": "SPIKEVAX",
                        "active_ingredient": "mRNA-1273",
                        "dosage_form": "INJECTION",
                        "route": "INTRAMUSCULAR",
                        "strength": "50 mcg/0.5mL",
                    }
                ],
                "action_type": "APPROVAL",
                "submission_type": "BLA",
                "approval_date": "20211218",
            }
        ]
    }


@pytest.fixture
def openfda_recall_payload() -> Dict[str, Any]:
    """Realistic openFDA recall/safety payload."""
    return {
        "results": [
            {
                "recall_number": "F-1234-2023",
                "product_description": "Drug X Tablets",
                "reason_for_recall": "Contamination",
                "recall_initiation_date": "20230315",
                "openfda": {
                    "brand_name": ["DrugX"],
                    "generic_name": ["active_ingredient_x"],
                },
            }
        ]
    }


@pytest.fixture
def clinical_trials_completed_payload() -> Dict[str, Any]:
    """Realistic ClinicalTrials completed trial payload."""
    return {
        "nct_id": "NCT04368728",
        "title": "Phase 3 Study of Drug Y in Condition Z",
        "status": "COMPLETED",
        "completion_date": "2023-06-15",
        "results_first_posted": "2023-09-20",
        "sponsor": "Pharma Corp",
        "has_results": True,
    }


@pytest.fixture
def clinical_trials_terminated_payload() -> Dict[str, Any]:
    """Realistic ClinicalTrials terminated trial payload."""
    return {
        "nct_id": "NCT04500000",
        "title": "Phase 2 Study of Drug Z in Rare Disease",
        "status": "TERMINATED",
        "why_stopped": "Safety concerns identified",
        "completion_date": "2023-03-10",
        "results_first_posted": None,
        "sponsor": "BioTech Inc",
        "has_results": False,
    }


# ========== openFDA Normalization Tests ==========


def test_normalize_openfda_approval(openfda_approval_payload):
    """Test normalization of openFDA approval into fda_decision event."""
    from src.tools.openfda_client import normalize_biotech_events

    events = normalize_biotech_events(openfda_approval_payload, source="openfda")

    assert len(events) > 0, "Should produce at least one event"
    event = events[0]

    # Verify required fields
    assert "id" in event
    assert "date" in event
    assert event["type"] == "fda_approval"
    assert event["sentiment"] == "positive"
    assert event["source"] == "openfda"
    assert event["priority"] == 1
    assert "ticker" in event
    assert "catalyst" in event
    assert event["ticker"] == "SPIKEVAX"

    # Verify date format YYYY-MM-DD
    assert len(event["date"]) == 10
    assert event["date"].count("-") == 2


def test_normalize_openfda_preserves_requested_ticker_attribution():
    """openFDA sponsor names must not replace the requested ticker ownership."""
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "BLA001",
                "sponsor_name": "ModernaTX, Inc.",
                "openfda": {
                    "brand_name": ["SPIKEVAX"],
                    "generic_name": ["mRNA-1273"],
                },
                "products": [
                    {
                        "brand_name": "SPIKEVAX",
                        "active_ingredient": "mRNA-1273",
                    }
                ],
                "action_type": "APPROVAL",
                "approval_date": "20260420",
            }
        ]
    }

    events = normalize_biotech_events(
        payload,
        source="openfda",
        requested_ticker=" mrna ",
    )

    assert len(events) == 1
    event = events[0]
    assert event["ticker"] == "MRNA"
    assert event["source_entity"] == "ModernaTX, Inc."
    assert event["source_ids"] == ["BLA001"]
    assert event["metadata"]["brand_names"] == ["SPIKEVAX"]


def test_normalize_openfda_recall(openfda_recall_payload):
    """Test normalization of openFDA recall into regulatory_change event."""
    from src.tools.openfda_client import normalize_biotech_events

    events = normalize_biotech_events(openfda_recall_payload, source="openfda")

    assert len(events) > 0, "Should produce at least one event"
    event = events[0]

    # Verify required fields
    assert event["type"] == "fda_recall"
    assert event["priority"] == 1
    assert event["source"] == "openfda"
    assert "id" in event
    assert "date" in event
    assert "catalyst" in event

    # Verify date format
    assert len(event["date"]) == 10


def test_normalize_openfda_legacy_no_brand_uses_sponsor_without_uppercasing():
    """Legacy openFDA fallback should preserve sponsor casing when no brand exists."""
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "ANDA001",
                "sponsor_name": "mixedCase pharma",
                "openfda": {"brand_name": []},
                "products": [{"brand_name": ""}],
                "action_type": "APPROVAL",
                "approval_date": "20240115",
            }
        ]
    }

    events = normalize_biotech_events(payload, source="openfda")

    assert len(events) == 1
    assert events[0]["ticker"] == "mixedCase pharma"


def test_normalize_openfda_legacy_no_brand_null_or_missing_sponsor_uses_unknown():
    """Legacy openFDA fallback should use UNKNOWN for null or missing sponsor."""
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "ANDA002",
                "sponsor_name": None,
                "openfda": {"brand_name": []},
                "products": [{"brand_name": ""}],
                "action_type": "APPROVAL",
                "approval_date": "20240116",
            },
            {
                "application_number": "ANDA003",
                "openfda": {"brand_name": []},
                "products": [{"brand_name": ""}],
                "action_type": "APPROVAL",
                "approval_date": "20240117",
            },
        ]
    }

    events = normalize_biotech_events(payload, source="openfda")

    assert [event["ticker"] for event in events] == ["UNKNOWN", "UNKNOWN"]


def test_normalize_openfda_uses_stable_ids_for_same_source_event():
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "BLA-STABLE",
                "sponsor_name": "Moderna Inc",
                "openfda": {"brand_name": ["SPIKEVAX"]},
                "products": [{"brand_name": "SPIKEVAX"}],
                "action_type": "APPROVAL",
                "approval_date": "20260420",
            }
        ]
    }

    first = normalize_biotech_events(payload, source="openfda", requested_ticker="MRNA")
    second = normalize_biotech_events(
        payload, source="openfda", requested_ticker="MRNA"
    )

    assert first[0]["id"] == second[0]["id"]


def test_normalize_openfda_approval_uses_real_submissions_shape():
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "BLA761223",
                "sponsor_name": "ModernaTX, Inc.",
                "openfda": {"brand_name": ["SPIKEVAX"]},
                "products": [{"brand_name": "SPIKEVAX"}],
                "submissions": [
                    {
                        "submission_type": "ORIG",
                        "submission_number": "1",
                        "submission_status": "AP",
                        "submission_status_date": "20260420",
                    }
                ],
            }
        ]
    }

    events = normalize_biotech_events(
        payload, source="openfda", requested_ticker="MRNA"
    )

    assert len(events) == 1
    assert events[0]["type"] == "fda_approval"
    assert events[0]["date"] == "2026-04-20"
    assert events[0]["priority"] == 1


def test_openfda_stable_ids_dedupe_inserted_events():
    from src.backtest.events_db import get_events, init_db, insert_events
    from src.tools.openfda_client import normalize_biotech_events

    payload = {
        "results": [
            {
                "application_number": "BLA-DEDUP",
                "sponsor_name": "Moderna Inc",
                "openfda": {"brand_name": ["SPIKEVAX"]},
                "products": [{"brand_name": "SPIKEVAX"}],
                "action_type": "APPROVAL",
                "approval_date": "20260420",
            }
        ]
    }
    events = normalize_biotech_events(
        payload, source="openfda", requested_ticker="MRNA"
    )

    init_db()
    assert insert_events(events) == 1
    assert insert_events(events) == 0

    rows = get_events("MRNA", start_date="2026-04-20", end_date="2026-04-20")
    assert rows["id"].tolist() == [events[0]["id"]]


def test_normalize_clinical_trials_completed(clinical_trials_completed_payload):
    """Test normalization of completed ClinicalTrials into clinical_readout event."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    events = normalize_biotech_events(
        [clinical_trials_completed_payload], source="clinicaltrials"
    )

    assert len(events) > 0, "Should produce at least one event"
    event = events[0]

    # Verify required fields
    assert event["type"] == "clinical_readout"
    assert event["sentiment"] == "positive"
    assert event["source"] == "clinicaltrials"
    assert event["priority"] in range(1, 6)
    assert "id" in event
    assert "date" in event
    assert "catalyst" in event
    assert event["ticker"] == "Pharma"

    # Verify date format
    assert len(event["date"]) == 10
    assert event["date"].count("-") == 2


def test_normalize_clinical_trials_coerces_public_metadata_shapes():
    """Public normalizer inputs should tolerate non-string sponsor and list conditions."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    payload = [
        {
            "nct_id": "NCT12345678",
            "title": "Phase 2 Study of Drug Q",
            "status": "COMPLETED",
            "completion_date": "2026-04-20",
            "results_first_posted": "2026-04-21",
            "sponsor": 12345,
            "has_results": True,
            "conditions": ["Melanoma", "Solid Tumor"],
            "phase": "Phase 2",
        }
    ]

    events = normalize_biotech_events(payload, source="clinicaltrials")

    assert len(events) == 1
    assert events[0]["ticker"] == "12345"
    assert events[0]["source_entity"] == "12345"
    assert events[0]["disease_area"] == "Melanoma"
    assert events[0]["metadata"]["raw_ticker"] == "12345"


def test_normalize_clinical_trials_preserves_requested_ticker_attribution():
    """ClinicalTrials sponsors must be attribution metadata, not event ownership."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    payload = [
        {
            "nct_id": "NCT00000001",
            "title": "A Study of mRNA-1273 in Respiratory Virus Prevention",
            "status": "COMPLETED",
            "completion_date": "2026-04-20",
            "results_first_posted": "2026-04-20",
            "sponsor": "ModernaTX, Inc.",
            "has_results": True,
            "conditions": "Respiratory Syncytial Virus",
            "phase": "Phase 3",
        }
    ]

    events = normalize_biotech_events(
        payload,
        source="clinicaltrials",
        requested_ticker=" mrna ",
    )

    assert len(events) == 1
    event = events[0]
    assert event["ticker"] == "MRNA"
    assert event["source_entity"] == "ModernaTX, Inc."
    assert event["source_ids"] == ["NCT00000001"]


def test_normalize_clinical_trials_terminated(clinical_trials_terminated_payload):
    """Test normalization of terminated ClinicalTrials into negative sentiment event."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    events = normalize_biotech_events(
        [clinical_trials_terminated_payload], source="clinicaltrials"
    )

    assert len(events) > 0, "Should produce at least one event"
    event = events[0]

    # Verify required fields
    assert event["type"] == "clinical_readout"
    assert event["sentiment"] == "negative"
    assert event["source"] == "clinicaltrials"
    assert "id" in event
    assert "date" in event
    assert "catalyst" in event

    # Verify date format
    assert len(event["date"]) == 10


def test_normalize_clinical_trials_missing_date():
    """Test that trials with no usable date are skipped."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    payload = {
        "nct_id": "NCT99999999",
        "title": "Trial with no dates",
        "status": "COMPLETED",
        "completion_date": None,
        "results_first_posted": None,
        "sponsor": "Unknown",
        "has_results": False,
    }

    events = normalize_biotech_events([payload], source="clinicaltrials")

    # Should skip records with no usable date
    assert len(events) == 0, "Should skip trials with no usable date"


def test_normalized_event_schema():
    """Verify the normalized event schema matches specification."""
    from src.tools.openfda_client import normalize_biotech_events as normalize_fda

    payload = {
        "results": [
            {
                "application_number": "BLA999999",
                "sponsor_name": "Test Pharma",
                "openfda": {
                    "brand_name": ["TestDrug"],
                    "generic_name": ["test_active"],
                },
                "products": [
                    {
                        "brand_name": "TestDrug",
                        "active_ingredient": "test_active",
                    }
                ],
                "action_type": "APPROVAL",
                "approval_date": "20230101",
            }
        ]
    }

    events = normalize_fda(payload, source="openfda")
    assert len(events) > 0

    event = events[0]
    required_keys = {
        "id",
        "date",
        "type",
        "priority",
        "ticker",
        "catalyst",
        "sentiment",
        "source",
    }
    assert required_keys.issubset(
        event.keys()
    ), f"Missing keys: {required_keys - set(event.keys())}"

    # Verify types
    assert isinstance(event["id"], str)
    assert isinstance(event["date"], str)
    assert isinstance(event["type"], str)
    assert isinstance(event["priority"], int)
    assert isinstance(event["ticker"], str)
    assert isinstance(event["catalyst"], str)
    assert isinstance(event["sentiment"], str)
    assert isinstance(event["source"], str)

    # Verify sentiment is one of allowed values
    assert event["sentiment"] in {"positive", "negative", "neutral"}


# ========== Event Ingestion Service Tests ==========


def test_fetch_log_table_init():
    """Test that fetch_log table is created successfully."""
    from src.backtest.events_db import init_fetch_log_table, _get_conn

    init_fetch_log_table()

    conn = _get_conn()
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fetch_log'"
    )
    assert cur.fetchone() is not None, "fetch_log table should exist"
    conn.close()


def test_record_fetch_attempt():
    """Test recording a fetch attempt with timestamp."""
    from src.backtest.events_db import (
        init_fetch_log_table,
        record_fetch_attempt,
        get_last_fetch_at,
        _get_conn,
    )

    init_fetch_log_table()

    # Clear any existing records
    conn = _get_conn()
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'TEST' AND source = 'openfda'")
    conn.commit()
    conn.close()

    # Record a fetch
    record_fetch_attempt("TEST", "openfda", 5)

    # Verify timestamp was recorded
    last_fetch = get_last_fetch_at("TEST", "openfda")
    assert last_fetch is not None, "Should have recorded fetch timestamp"
    assert len(last_fetch) > 0, "Timestamp should not be empty"


def test_empty_result_caching():
    """Test that empty-result fetches still record a timestamp."""
    from src.backtest.events_db import (
        init_fetch_log_table,
        record_fetch_attempt,
        get_last_fetch_at,
        _get_conn,
    )

    init_fetch_log_table()

    # Clear any existing records
    conn = _get_conn()
    conn.execute(
        "DELETE FROM fetch_log WHERE ticker = 'EMPTY' AND source = 'clinicaltrials'"
    )
    conn.commit()
    conn.close()

    # Record a fetch with zero items
    record_fetch_attempt("EMPTY", "clinicaltrials", 0)

    # Verify timestamp was recorded even with zero items
    last_fetch = get_last_fetch_at("EMPTY", "clinicaltrials")
    assert last_fetch is not None, "Should record timestamp even for empty results"


def test_cache_freshness_logic():
    """Test that cache freshness is correctly evaluated."""
    from src.services.event_ingestion_service import _is_cache_stale
    from datetime import datetime, timedelta

    # None should be stale
    assert _is_cache_stale(None, 6) is True

    # Recent timestamp should not be stale
    recent = (datetime.now() - timedelta(hours=2)).isoformat()
    assert _is_cache_stale(recent, 6) is False

    # Old timestamp should be stale
    old = (datetime.now() - timedelta(hours=8)).isoformat()
    assert _is_cache_stale(old, 6) is True

    # Edge case: just past boundary should be stale
    past_boundary = (datetime.now() - timedelta(hours=6, minutes=1)).isoformat()
    assert _is_cache_stale(past_boundary, 6) is True


def test_ingestion_service_first_request_fetches():
    """Test that first request fetches from sources and writes DB."""
    from src.services.event_ingestion_service import get_events_for_ticker
    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from unittest.mock import patch, MagicMock

    init_db()
    init_fetch_log_table()

    # Clear test data
    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'TESTFIRST'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'TESTFIRST'")
    conn.commit()
    conn.close()

    # Mock the API clients
    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, patch(
        "src.services.event_ingestion_service.search_trials"
    ) as mock_trials:

        # Mock openFDA response
        mock_fda_instance = MagicMock()
        mock_fda.return_value = mock_fda_instance
        mock_fda_instance.collect.return_value = {
            "label": {"results": []},
            "event": {"results": []},
            "drugsfda": {
                "results": [
                    {
                        "application_number": "BLA001",
                        "sponsor_name": "TestCorp",
                        "openfda": {"brand_name": ["TestDrug"]},
                        "products": [{"brand_name": "TestDrug"}],
                        "action_type": "APPROVAL",
                        "approval_date": "20230101",
                    }
                ]
            },
        }

        # Mock ClinicalTrials response
        mock_trials.return_value = []

        # First request should fetch
        events = get_events_for_ticker("TESTFIRST", max_age_hours=6)

        # Verify fetch was called
        mock_fda_instance.collect.assert_called_once()
        mock_trials.assert_called_once()

        # Verify fetch log was recorded
        from src.backtest.events_db import get_last_fetch_at

        assert get_last_fetch_at("TESTFIRST", "openfda") is not None
        assert get_last_fetch_at("TESTFIRST", "clinicaltrials") is not None


def test_ingestion_service_cache_hit():
    """Test that second request within 6h does not hit external sources."""
    from src.services.event_ingestion_service import get_events_for_ticker
    from src.backtest.events_db import (
        init_db,
        init_fetch_log_table,
        _get_conn,
    )
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timedelta

    init_db()
    init_fetch_log_table()

    # Clear and setup test data
    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'TESTCACHE'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'TESTCACHE'")
    conn.commit()

    # Pre-populate fetch log with recent timestamps (2 hours ago)
    recent_time = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        ("TESTCACHE", "openfda", recent_time, 1),
    )
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        ("TESTCACHE", "clinicaltrials", recent_time, 0),
    )
    conn.commit()
    conn.close()

    # Mock the API clients
    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, patch(
        "src.services.event_ingestion_service.search_trials"
    ) as mock_trials:

        mock_fda_instance = MagicMock()
        mock_fda.return_value = mock_fda_instance

        # Second request should NOT call the APIs (cache hit)
        events = get_events_for_ticker("TESTCACHE", max_age_hours=6)

        # Verify APIs were NOT called
        mock_fda_instance.collect.assert_not_called()
        mock_trials.assert_not_called()


def test_event_db_roundtrips_source_ids_and_metadata():
    """Event DB should persist structured attribution fields as decoded objects."""
    from src.backtest.events_db import (
        init_db,
        insert_event,
        get_events_for_chart,
        _get_conn,
    )

    init_db()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'ROUNDTRIP'")
    conn.commit()
    conn.close()

    insert_event(
        {
            "id": "roundtrip-event-1",
            "date": "2026-04-20",
            "type": "clinical_readout",
            "priority": 4,
            "ticker": "ROUNDTRIP",
            "disease_area": "Oncology",
            "catalyst": "Clinical Trial: Phase 3 readout",
            "sentiment": "positive",
            "price_impact": None,
            "source": "clinicaltrials",
            "source_entity": "ModernaTX, Inc.",
            "source_url": "https://clinicaltrials.gov/study/NCT00000001",
            "source_ids": ["NCT00000001"],
            "confidence": "high",
            "metadata": {"phase": "Phase 3", "has_results": True},
        }
    )

    rows = get_events_for_chart("ROUNDTRIP")

    assert len(rows) == 1
    assert rows[0]["source_entity"] == "ModernaTX, Inc."
    assert rows[0]["source_url"] == "https://clinicaltrials.gov/study/NCT00000001"
    assert rows[0]["source_ids"] == ["NCT00000001"]
    assert rows[0]["confidence"] == "high"
    assert rows[0]["metadata"] == {"phase": "Phase 3", "has_results": True}


def test_event_db_insert_applies_optional_field_defaults():
    """Event inserts should apply defaults for omitted optional bound fields."""
    import pandas as pd

    from src.backtest.events_db import (
        init_db,
        insert_event,
        get_events_for_chart,
        _get_conn,
    )

    init_db()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'DEFAULTS'")
    conn.commit()
    conn.close()

    insert_event(
        {
            "id": "defaults-event-1",
            "date": "2026-04-22",
            "type": "clinical_readout",
            "ticker": "DEFAULTS",
            "disease_area": "Oncology",
            "catalyst": "Clinical Trial: defaulted fields",
            "source": "clinicaltrials",
        }
    )

    rows = get_events_for_chart("DEFAULTS")

    assert len(rows) == 1
    assert rows[0]["priority"] == 3
    assert rows[0]["sentiment"] == "neutral"
    assert pd.isna(rows[0]["price_impact"])
    assert rows[0]["source_ids"] == []
    assert rows[0]["metadata"] == {}
    assert rows[0]["confidence"] == "medium"


def test_event_db_insert_migrates_old_shape_table_without_init_db():
    """Insert paths should migrate an existing old-shape table before binding new columns."""
    from src.backtest.events_db import insert_event, get_events_for_chart, _get_conn

    conn = _get_conn()
    conn.execute("""
        CREATE TABLE biotech_events (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 3,
            ticker TEXT NOT NULL,
            disease_area TEXT,
            catalyst TEXT,
            sentiment TEXT DEFAULT 'neutral',
            price_impact REAL,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
    conn.commit()
    conn.close()

    insert_event(
        {
            "id": "old-shape-event-1",
            "date": "2026-04-23",
            "type": "clinical_readout",
            "ticker": "OLDSHAPE",
            "disease_area": "Oncology",
            "catalyst": "Clinical Trial: migrated table",
            "source": "clinicaltrials",
        }
    )

    rows = get_events_for_chart("OLDSHAPE")

    assert len(rows) == 1
    assert rows[0]["priority"] == 3
    assert rows[0]["sentiment"] == "neutral"
    assert rows[0]["source_ids"] == []
    assert rows[0]["metadata"] == {}
    assert rows[0]["confidence"] == "medium"


def test_event_db_decodes_legacy_rows_with_default_attribution_fields():
    """Existing rows without structured metadata should still decode safely."""
    from src.backtest.events_db import init_db, get_events_for_chart, _get_conn

    init_db()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'LEGACYROW'")
    conn.execute(
        """
        INSERT INTO biotech_events
        (id, date, type, priority, ticker, disease_area, catalyst, sentiment, price_impact, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-row-1",
            "2026-04-21",
            "fda_decision",
            5,
            "LEGACYROW",
            "",
            "FDA Approval: LegacyDrug",
            "positive",
            None,
            "openfda",
        ),
    )
    conn.commit()
    conn.close()

    rows = get_events_for_chart("LEGACYROW")

    assert len(rows) == 1
    assert rows[0]["source_ids"] == []
    assert rows[0]["metadata"] == {}
    assert rows[0]["confidence"] == "medium"


def test_get_source_statuses_for_ticker_returns_fetch_log_rows():
    """Status helper should expose fetch attempts for the requested ticker."""
    from src.backtest.events_db import (
        init_fetch_log_table,
        record_fetch_attempt,
        _get_conn,
    )
    from src.services.event_ingestion_service import get_source_statuses_for_ticker

    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'STATUS'")
    conn.commit()
    conn.close()

    record_fetch_attempt("STATUS", "clinicaltrials", 2)
    record_fetch_attempt("STATUS", "openfda", 1)

    rows = get_source_statuses_for_ticker("STATUS")

    assert [row["source"] for row in rows] == ["clinicaltrials", "openfda"]
    assert [row["item_count"] for row in rows] == [2, 1]
    assert all(row["last_fetch_at"] for row in rows)


def test_fetch_log_preserves_error_status_and_message():
    """Fetch status rows should distinguish failed sources from empty sources."""
    from src.backtest.events_db import (
        init_fetch_log_table,
        record_fetch_attempt,
        _get_conn,
    )
    from src.services.event_ingestion_service import get_source_statuses_for_ticker

    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'STATUSERR'")
    conn.commit()
    conn.close()

    record_fetch_attempt(
        "STATUSERR",
        "openfda",
        0,
        status="rate_limited",
        message="429 Too Many Requests",
    )

    rows = get_source_statuses_for_ticker("STATUSERR")

    assert rows == [
        {
            "source": "openfda",
            "last_fetch_at": rows[0]["last_fetch_at"],
            "item_count": 0,
            "status": "rate_limited",
            "message": "429 Too Many Requests",
        }
    ]
    assert rows[0]["last_fetch_at"]


def test_ingestion_records_error_status_when_source_fetch_fails():
    """Source exceptions should be visible to Kline status panels."""
    from unittest.mock import patch

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services.event_ingestion_service import (
        get_events_for_ticker,
        get_source_statuses_for_ticker,
    )

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'ERRSTAT'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'ERRSTAT'")
    conn.commit()
    conn.close()

    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, patch(
        "src.services.event_ingestion_service.search_trials"
    ) as mock_trials:
        mock_fda.return_value.collect.side_effect = RuntimeError(
            "429 Too Many Requests"
        )
        mock_trials.return_value = []

        get_events_for_ticker("ERRSTAT", max_age_hours=0)

    rows = get_source_statuses_for_ticker("ERRSTAT")
    by_source = {row["source"]: row for row in rows}

    assert by_source["openfda"]["status"] == "rate_limited"
    assert by_source["openfda"]["message"] == "429 Too Many Requests"
    assert by_source["clinicaltrials"]["status"] == "empty"


@pytest.mark.parametrize(
    ("gdelt_events", "expected_status"),
    [
        ([], "empty"),
        (
            [
                {
                    "id": "gdelt-ready-1",
                    "date": "2026-04-20",
                    "type": "macro",
                    "priority": 3,
                    "ticker": "GDELTREADY",
                    "catalyst": "GDELT macro event",
                    "sentiment": "neutral",
                    "source": "gdelt",
                }
            ],
            "ready",
        ),
    ],
)
def test_ingestion_records_explicit_gdelt_success_status(
    gdelt_events,
    expected_status,
    monkeypatch,
):
    """GDELT success rows should not rely on fetch-log default status inference."""
    from datetime import datetime, timedelta

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services import event_ingestion_service

    ticker = f"GDELT{expected_status.upper()}"

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM fetch_log WHERE ticker = ?", (ticker,))
    recent_time = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        (ticker, "openfda", recent_time, 0),
    )
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        (ticker, "clinicaltrials", recent_time, 0),
    )
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        (ticker, "alphavantage", recent_time, 0),
    )
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        (ticker, "macro_regime", recent_time, 0),
    )
    conn.commit()
    conn.close()

    attempts = []
    fetch_calls = []

    def record_fetch_attempt_spy(*args, **kwargs):
        attempts.append((args, kwargs))

    def fetch_gdelt_spy(query, max_records=20, raise_on_error=False):
        fetch_calls.append((query, max_records, raise_on_error))
        return gdelt_events

    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_biotech_macro_events",
        fetch_gdelt_spy,
    )
    monkeypatch.setattr(event_ingestion_service, "insert_events", lambda events: None)
    monkeypatch.setattr(
        event_ingestion_service,
        "record_fetch_attempt",
        record_fetch_attempt_spy,
    )

    event_ingestion_service.get_events_for_ticker(ticker, max_age_hours=6)

    assert fetch_calls == [(ticker, 20, True)]
    assert attempts == [
        ((ticker, "gdelt", len(gdelt_events)), {"status": expected_status})
    ]


def test_ingestion_records_explicit_macro_regime_success_status(monkeypatch):
    """Macro regime success rows should expose normal source readiness state."""
    from datetime import datetime, timedelta

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services import event_ingestion_service

    ticker = "MACROREADY"

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM fetch_log WHERE ticker = ?", (ticker,))
    recent_time = (datetime.now() - timedelta(hours=2)).isoformat()
    for source in ("openfda", "clinicaltrials", "alphavantage", "gdelt"):
        conn.execute(
            "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
            (ticker, source, recent_time, 0),
        )
    conn.commit()
    conn.close()

    attempts = []
    fetch_calls = []

    def record_fetch_attempt_spy(*args, **kwargs):
        attempts.append((args, kwargs))

    def fetch_macro_regime_spy(requested_ticker):
        fetch_calls.append(requested_ticker)
        return [
            {
                "id": "macro-ready-1",
                "date": "2026-04-24",
                "type": "macro_risk_off",
                "category": "macro",
                "priority": 2,
                "ticker": requested_ticker,
                "disease_area": "",
                "catalyst": "VIX risk-off regime at 31.0",
                "sentiment": "negative",
                "price_impact": None,
                "source": "macro_regime",
                "source_entity": "^VIX",
                "source_ids": ["^VIX"],
                "metadata": {
                    "benchmark": "^VIX",
                    "level": 31.0,
                    "backtest_eligible": True,
                },
            }
        ]

    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_macro_regime_events",
        fetch_macro_regime_spy,
        raising=False,
    )
    monkeypatch.setattr(event_ingestion_service, "insert_events", lambda events: None)
    monkeypatch.setattr(
        event_ingestion_service,
        "record_fetch_attempt",
        record_fetch_attempt_spy,
    )

    event_ingestion_service.get_events_for_ticker(ticker, max_age_hours=6)

    assert fetch_calls == [ticker]
    assert attempts == [
        ((ticker, "macro_regime", 1), {"status": "ready"})
    ]


def test_gdelt_client_can_raise_fetch_errors(monkeypatch):
    """GDELT fetch errors should be exposable to source-status recording."""
    import requests

    from src.tools import gdelt_client

    def fail_request(*args, **kwargs):
        raise requests.HTTPError("429 Too Many Requests")

    monkeypatch.setattr(gdelt_client.requests, "get", fail_request)

    with pytest.raises(requests.HTTPError, match="429 Too Many Requests"):
        gdelt_client.fetch_biotech_macro_events("MRNA", raise_on_error=True)


def test_ingestion_records_openfda_client_http_failure_status():
    """Real openFDA HTTP failures should not be flattened into empty source status."""
    import requests
    from unittest.mock import MagicMock, patch

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services.event_ingestion_service import (
        get_events_for_ticker,
        get_source_statuses_for_ticker,
    )

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'FDAHTTPERR'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'FDAHTTPERR'")
    conn.commit()
    conn.close()

    failed_response = MagicMock()
    failed_response.raise_for_status.side_effect = requests.HTTPError(
        "429 Too Many Requests"
    )

    with patch(
        "src.tools.openfda_client.requests.Session.get",
        return_value=failed_response,
    ), patch("src.services.event_ingestion_service.search_trials") as mock_trials:
        mock_trials.return_value = []

        get_events_for_ticker("FDAHTTPERR", max_age_hours=0)

    rows = get_source_statuses_for_ticker("FDAHTTPERR")
    by_source = {row["source"]: row for row in rows}

    assert by_source["openfda"]["status"] == "rate_limited"
    assert "429 Too Many Requests" in by_source["openfda"]["message"]
    assert by_source["clinicaltrials"]["status"] == "empty"


def test_ingestion_records_openfda_no_matches_as_empty_status():
    """openFDA 404 no-match responses should remain empty, not source failures."""
    import requests
    from unittest.mock import MagicMock, patch

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services.event_ingestion_service import (
        get_events_for_ticker,
        get_source_statuses_for_ticker,
    )

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'FDANOMATCH'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'FDANOMATCH'")
    conn.commit()
    conn.close()

    not_found_response = MagicMock()
    not_found_response.status_code = 404
    not_found_response.raise_for_status.side_effect = requests.HTTPError(
        "404 Client Error: Not Found for url"
    )

    with patch(
        "src.tools.openfda_client.requests.Session.get",
        return_value=not_found_response,
    ), patch("src.services.event_ingestion_service.search_trials") as mock_trials:
        mock_trials.return_value = []

        get_events_for_ticker("FDANOMATCH", max_age_hours=0)

    rows = get_source_statuses_for_ticker("FDANOMATCH")
    by_source = {row["source"]: row for row in rows}

    assert by_source["openfda"]["status"] == "empty"
    assert by_source["openfda"]["message"] is None
    assert by_source["clinicaltrials"]["status"] == "empty"


def test_ingestion_records_clinicaltrials_request_failure_status():
    """Real ClinicalTrials request exhaustion should not be flattened into empty status."""
    import requests
    from unittest.mock import patch

    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services.event_ingestion_service import (
        get_events_for_ticker,
        get_source_statuses_for_ticker,
    )

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'CTHTTPERR'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'CTHTTPERR'")
    conn.commit()
    conn.close()

    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, patch(
        "src.tools.clinical_trials_client.requests.get"
    ) as mock_get, patch("src.tools.clinical_trials_client.time.sleep"):
        mock_fda.return_value.collect.return_value = {
            "label": {"results": []},
            "event": {"results": []},
            "drugsfda": {"results": []},
        }
        mock_get.side_effect = requests.RequestException("503 Service Unavailable")

        get_events_for_ticker("CTHTTPERR", max_age_hours=0)

    rows = get_source_statuses_for_ticker("CTHTTPERR")
    by_source = {row["source"]: row for row in rows}

    assert by_source["openfda"]["status"] == "empty"
    assert by_source["clinicaltrials"]["status"] == "error"
    assert "503 Service Unavailable" in by_source["clinicaltrials"]["message"]


def test_normalize_clinical_trial_milestone_events_expands_key_dates():
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000001",
                "title": "A Phase 3 Study",
                "status": "COMPLETED",
                "sponsor": "ModernaTX, Inc.",
                "conditions": "Melanoma",
                "interventions": "mRNA-4157",
                "phase": "Phase 3",
                "has_results": True,
                "primary_completion_date": "2026-04-18",
                "completion_date": "2026-04-19",
                "results_first_posted": "2026-04-20",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert [event["type"] for event in events] == [
        "trial_results_posted",
        "trial_primary_completion",
        "trial_completion",
        "trial_status_change",
    ]
    assert all(event["ticker"] == "MRNA" for event in events)
    assert all(event["source_ids"] == ["NCT00000001"] for event in events)
    assert all(event["metadata"]["source_tier"] == "official" for event in events)


def test_normalize_clinical_trial_milestone_events_emits_termination():
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000002",
                "title": "A Stopped Phase 2 Study",
                "status": "TERMINATED",
                "why_stopped": "Safety concerns",
                "sponsor": "ModernaTX, Inc.",
                "conditions": "Melanoma",
                "phase": "Phase 2",
                "has_results": False,
                "completion_date": "2026-04-19",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert [event["type"] for event in events] == [
        "trial_termination",
        "trial_status_change",
    ]
    assert events[0]["sentiment"] == "negative"
    assert events[0]["metadata"]["why_stopped"] == "Safety concerns"


def test_normalize_clinical_trial_milestones_drops_unowned_ticker_matches():
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000003",
                "title": "Academic mRNA vaccine study",
                "status": "COMPLETED",
                "sponsor": "Example University",
                "collaborators": "Pfizer Inc.",
                "conditions": "Influenza",
                "interventions": "mRNA vaccine candidate",
                "phase": "Phase 2",
                "has_results": True,
                "completion_date": "2026-04-19",
                "results_first_posted": "2026-04-20",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert events == []


def test_normalize_clinical_trial_milestones_rejects_company_prefix_false_positive():
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000005",
                "title": "Modern analytics mRNA vaccine study",
                "status": "COMPLETED",
                "sponsor": "Modern Analytics Institute",
                "collaborators": "None",
                "conditions": "Influenza",
                "interventions": "mRNA vaccine candidate",
                "phase": "Phase 2",
                "has_results": True,
                "completion_date": "2026-04-19",
                "results_first_posted": "2026-04-20",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert events == []


def test_normalize_clinical_trial_milestones_accepts_collaborator_ownership():
    from src.tools.clinical_trials_client import (
        normalize_clinical_trial_milestone_events,
    )

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000004",
                "title": "Investigator-sponsored Moderna vaccine study",
                "status": "COMPLETED",
                "sponsor": "Example University",
                "collaborators": "ModernaTX, Inc.",
                "conditions": "Melanoma",
                "interventions": "mRNA-4157",
                "phase": "Phase 2",
                "has_results": True,
                "completion_date": "2026-04-19",
                "results_first_posted": "2026-04-20",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert events
    assert all(event["ticker"] == "MRNA" for event in events)
    assert all(event["metadata"]["entity_match"] == "collaborator" for event in events)


def test_ingestion_records_alphavantage_disabled_when_key_missing(monkeypatch):
    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services import event_ingestion_service

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'AVDISABLED'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'AVDISABLED'")
    conn.commit()
    conn.close()

    class EmptyFDA:
        def collect(self, ticker, limit=20):
            return {
                "label": {"results": []},
                "event": {"results": []},
                "drugsfda": {"results": []},
            }

    monkeypatch.setattr(
        event_ingestion_service, "OpenFDAClient", lambda *args, **kwargs: EmptyFDA()
    )
    monkeypatch.setattr(
        event_ingestion_service, "search_trials", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_biotech_macro_events",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_market_news_events",
        lambda ticker: (
            [],
            {
                "source": "alphavantage",
                "status": "disabled",
                "item_count": 0,
                "message": "ALPHA_VANTAGE_API_KEY is not set",
            },
        ),
    )

    event_ingestion_service.get_events_for_ticker("AVDISABLED", max_age_hours=0)
    rows = event_ingestion_service.get_source_statuses_for_ticker("AVDISABLED")
    by_source = {row["source"]: row for row in rows}

    assert by_source["alphavantage"]["status"] == "disabled"
    assert "ALPHA_VANTAGE_API_KEY" in by_source["alphavantage"]["message"]


def test_alphavantage_disabled_cache_refreshes_after_api_key_is_set(monkeypatch):
    from src.backtest.events_db import (
        init_db,
        init_fetch_log_table,
        record_fetch_attempt,
    )
    from src.services import event_ingestion_service

    ticker = "AVKEYREADY"
    init_db()
    init_fetch_log_table()
    for source in ("openfda", "clinicaltrials", "gdelt"):
        record_fetch_attempt(ticker, source, 0, status="empty")
    record_fetch_attempt(
        ticker,
        "alphavantage",
        0,
        status="disabled",
        message="ALPHA_VANTAGE_API_KEY is not set",
    )

    fetch_calls: list[str] = []

    def fetch_news(ticker):
        fetch_calls.append(ticker)
        return (
            [
                {
                    "id": "av-key-ready",
                    "date": "2026-04-20",
                    "type": "market_news",
                    "category": "news",
                    "priority": 3,
                    "ticker": ticker,
                    "catalyst": "Alpha Vantage news",
                    "sentiment": "positive",
                    "source": "alphavantage",
                    "metadata": {},
                }
            ],
            {"source": "alphavantage", "status": "ready", "message": None},
        )

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")
    monkeypatch.setattr(event_ingestion_service, "fetch_market_news_events", fetch_news)
    monkeypatch.setattr(
        event_ingestion_service, "insert_events", lambda events: len(events)
    )

    event_ingestion_service.get_events_for_ticker(ticker, max_age_hours=24)

    assert fetch_calls == [ticker]


def test_ingestion_enriches_openfda_and_gdelt_events_before_insert(monkeypatch):
    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services import event_ingestion_service

    ticker = "ENRICHMETA"
    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM fetch_log WHERE ticker = ?", (ticker,))
    conn.commit()
    conn.close()

    class FDA:
        def collect(self, ticker, limit=20):
            return {
                "label": {"results": []},
                "event": {"results": []},
                "drugsfda": {
                    "results": [
                        {
                            "application_number": "BLA999",
                            "sponsor_name": "Enrich Bio",
                            "openfda": {"brand_name": ["EnrichDrug"]},
                            "products": [{"brand_name": "EnrichDrug"}],
                            "action_type": "APPROVAL",
                            "approval_date": "20260420",
                        }
                    ]
                },
            }

    inserted: list[dict] = []

    def capture_insert(events):
        inserted.extend(events)
        return len(events)

    monkeypatch.setattr(
        event_ingestion_service, "OpenFDAClient", lambda *args, **kwargs: FDA()
    )
    monkeypatch.setattr(
        event_ingestion_service, "search_trials", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_market_news_events",
        lambda ticker: (
            [],
            {
                "source": "alphavantage",
                "status": "disabled",
                "item_count": 0,
                "message": "ALPHA_VANTAGE_API_KEY is not set",
            },
        ),
    )
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_biotech_macro_events",
        lambda *args, **kwargs: [
            {
                "id": "gdelt-enrich",
                "date": "2026-04-21",
                "type": "macro_economic",
                "priority": 3,
                "ticker": ticker,
                "catalyst": "Macro biotech policy update",
                "sentiment": "neutral",
                "source": "gdelt",
            }
        ],
    )
    monkeypatch.setattr(event_ingestion_service, "insert_events", capture_insert)

    event_ingestion_service.get_events_for_ticker(ticker, max_age_hours=0)

    by_source = {event["source"]: event for event in inserted}
    assert by_source["openfda"]["metadata"]["source_tier"] == "official"
    assert by_source["openfda"]["metadata"]["backtest_eligible"] is True
    assert by_source["openfda"]["metadata"]["confidence_score"] >= 0.7
    assert by_source["gdelt"]["metadata"]["source_tier"] == "macro"
    assert by_source["gdelt"]["metadata"]["backtest_eligible"] is False
    assert "impact_score" in by_source["gdelt"]["metadata"]
