"""
Tests for biotech event normalization from openFDA and ClinicalTrials.

These tests verify that raw API payloads are correctly normalized into
a consistent biotech_events schema for downstream analysis.
"""

import pytest
from datetime import datetime
from typing import Dict, Any


# ========== Test Fixtures ==========

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
    assert event["type"] == "fda_decision"
    assert event["sentiment"] == "positive"
    assert event["source"] == "openfda"
    assert event["priority"] in range(1, 6)
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
    assert event["type"] == "regulatory_change"
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


def test_normalize_clinical_trials_completed(clinical_trials_completed_payload):
    """Test normalization of completed ClinicalTrials into clinical_readout event."""
    from src.tools.clinical_trials_client import normalize_biotech_events

    events = normalize_biotech_events(
        [clinical_trials_completed_payload],
        source="clinicaltrials"
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
        [clinical_trials_terminated_payload],
        source="clinicaltrials"
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
    required_keys = {"id", "date", "type", "priority", "ticker", "catalyst", "sentiment", "source"}
    assert required_keys.issubset(event.keys()), f"Missing keys: {required_keys - set(event.keys())}"

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
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'EMPTY' AND source = 'clinicaltrials'")
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
    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, \
         patch("src.services.event_ingestion_service.search_trials") as mock_trials:

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
        ("TESTCACHE", "openfda", recent_time, 1)
    )
    conn.execute(
        "INSERT INTO fetch_log (ticker, source, last_fetch_at, item_count) VALUES (?, ?, ?, ?)",
        ("TESTCACHE", "clinicaltrials", recent_time, 0)
    )
    conn.commit()
    conn.close()

    # Mock the API clients
    with patch("src.services.event_ingestion_service.OpenFDAClient") as mock_fda, \
         patch("src.services.event_ingestion_service.search_trials") as mock_trials:

        mock_fda_instance = MagicMock()
        mock_fda.return_value = mock_fda_instance

        # Second request should NOT call the APIs (cache hit)
        events = get_events_for_ticker("TESTCACHE", max_age_hours=6)

        # Verify APIs were NOT called
        mock_fda_instance.collect.assert_not_called()
        mock_trials.assert_not_called()


def test_event_db_roundtrips_source_ids_and_metadata():
    """Event DB should persist structured attribution fields as decoded objects."""
    from src.backtest.events_db import init_db, insert_event, get_events_for_chart, _get_conn

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
    from src.backtest.events_db import init_fetch_log_table, record_fetch_attempt, _get_conn
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
