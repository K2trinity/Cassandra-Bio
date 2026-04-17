# tests/test_disease_survey_models.py
"""Tests for disease survey data models."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.engines.report_engine.disease_survey.models import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
)


def test_drug_asset_minimal():
    asset = DrugAsset(asset_name="Lecanemab", sponsor="Eisai")
    assert asset.asset_name == "Lecanemab"
    assert asset.targets == []
    assert asset.phase is None


def test_drug_asset_full():
    asset = DrugAsset(
        asset_name="Lecanemab",
        aliases=["BAN2401"],
        modality="Monoclonal Antibody",
        targets=["Aβ"],
        sponsor="Eisai",
        phase="Phase 3",
        status="Approved",
        trial_ids=["NCT01767311"],
        indication_subtype="Early AD",
    )
    assert asset.aliases == ["BAN2401"]
    assert "Aβ" in asset.targets


def test_trial_record_minimal():
    trial = TrialRecord(nct_id="NCT01767311", title="Clarity AD")
    assert trial.nct_id == "NCT01767311"
    assert trial.enrollment is None


def test_sponsor_profile_with_financials():
    sp = SponsorProfile(
        company_name="Eisai",
        pipeline_count=3,
        lead_phase="Phase 3",
        ticker="ESALY",
        market_cap=30e9,
    )
    assert sp.pipeline_count == 3
    assert sp.ticker == "ESALY"


def test_cns_benchmark_entry():
    entry = CNSBenchmarkEntry(
        target_name="Aβ",
        publication_count_5yr=120,
        trial_count_5yr=45,
        top_journal_citations=30,
        trend="rising",
        matched=True,
    )
    assert entry.matched is True
    assert entry.trend == "rising"


def test_literature_record():
    rec = LiteratureRecord(pmid="12345678", title="Amyloid cascade hypothesis revisited")
    assert rec.journal is None
    assert rec.year is None


def test_disease_survey_state_minimal():
    state = DiseaseSurveyState(disease_name="Alzheimer's Disease", query="AD drug pipeline")
    assert state.drug_assets == []
    assert state.trials == []
    assert state.sponsors == []
    assert state.literature == []
    assert state.cns_benchmark == []
    assert state.summary_text is None
    assert isinstance(state.generated_at, datetime)


def test_disease_survey_state_rejects_int_for_str():
    # Pydantic v2 does NOT coerce int to str — it raises ValidationError
    with pytest.raises(ValidationError):
        DiseaseSurveyState(disease_name=123, query="test")


def test_disease_survey_state_rejects_missing_required():
    with pytest.raises(ValidationError):
        DiseaseSurveyState(query="test")  # disease_name is required
