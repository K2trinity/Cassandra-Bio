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

    # Verify date format YYYY-MM-DD
    assert len(event["date"]) == 10
    assert event["date"].count("-") == 2


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

    # Verify date format
    assert len(event["date"]) == 10
    assert event["date"].count("-") == 2


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
