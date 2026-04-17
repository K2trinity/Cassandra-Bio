"""Tests for disease survey composer."""
import pytest
from src.engines.report_engine.disease_survey import (
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
    aggregate_survey_data,
)
from src.engines.report_engine.disease_survey.composer import compose_disease_survey_report


def make_state():
    return DiseaseSurveyState(
        disease_name="Alzheimer's Disease",
        query="AD pipeline",
        drug_assets=[DrugAsset(asset_name="Lecanemab", targets=["Aβ"], sponsor="Eisai", phase="Phase 3")],
        trials=[TrialRecord(nct_id="NCT01767311", title="Clarity AD", phase="Phase 3")],
        sponsors=[SponsorProfile(company_name="Eisai", pipeline_count=1)],
        literature=[LiteratureRecord(pmid="1", title="Test paper", year=2023)],
    )


def test_compose_returns_all_sections():
    state = make_state()
    report = compose_disease_survey_report(state)
    expected_sections = [
        "executive_summary", "drug_pipeline", "trial_landscape",
        "sponsor_analysis", "target_biology", "safety_profile",
        "literature_review", "cns_benchmark", "market_landscape",
    ]
    for section in expected_sections:
        assert section in report, f"Missing section: {section}"


def test_compose_empty_state():
    state = DiseaseSurveyState(disease_name="Unknown", query="test")
    report = compose_disease_survey_report(state)
    assert report["executive_summary"]["total_assets"] == 0
    assert report["drug_pipeline"]["assets"] == []


def test_public_api_imports():
    from src.engines.report_engine.disease_survey import (
        aggregate_survey_data,
        render_executive_summary,
        render_drug_pipeline,
        DiseaseSurveyState,
        DrugAsset,
    )
    assert callable(aggregate_survey_data)
    assert callable(render_executive_summary)
