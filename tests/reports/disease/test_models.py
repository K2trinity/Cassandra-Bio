from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseChapterNarratives,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


def test_clinical_trial_record_carries_landscape_fields():
    record = ClinicalTrialRecord(
        study_title="A Study of Donanemab in Early Symptomatic Alzheimer Disease",
        nct_number="NCT00000001",
        status="RECRUITING",
        phases=["PHASE2"],
        has_results=False,
        study_results="No posted results",
        results_url="https://clinicaltrials.gov/study/NCT00000001/results",
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor="Eli Lilly and Company",
        study_type="INTERVENTIONAL",
        enrollment=1200,
        primary_outcome_measures=["Change from baseline in iADRS"],
        secondary_outcome_measures=["Change from baseline in CDR-SB"],
        study_first_posted=date(2026, 4, 20),
        results_first_posted=None,
        last_update_posted=date(2026, 4, 22),
        start_date=date(2026, 5, 1),
        primary_completion_date=date(2029, 5, 1),
        completion_date=None,
        strata=["frontier"],
        primary_stratum="frontier",
        source_url="https://clinicaltrials.gov/study/NCT00000001",
    )

    payload = record.model_dump()

    assert payload["phases"] == ["PHASE2"]
    assert payload["status"] == "RECRUITING"
    assert payload["has_results"] is False
    assert payload["study_results"] == "No posted results"
    assert payload["enrollment"] == 1200
    assert payload["primary_outcome_measures"] == ["Change from baseline in iADRS"]
    assert payload["strata"] == ["frontier"]
    assert payload["primary_stratum"] == "frontier"


def test_clinical_trial_record_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ClinicalTrialRecord(
            study_title="Noise row",
            nct_number="NCT00000002",
            status="UNKNOWN",
            conditions=["Alzheimer Disease"],
            interventions=[],
            sponsor="Unknown",
            study_type="OBSERVATIONAL",
            source_url="https://clinicaltrials.gov/study/NCT00000002",
            unsupported_field="not allowed",
        )


def test_disease_report_package_carries_handoff_contract():
    profile = DiseaseProfile(
        query="conduct a comprehensive survey on Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease", "Alzheimer's Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D&viewType=Card&sort=StudyFirstPostDate",
    )
    trial = ClinicalTrialRecord(
        study_title="A Study in Alzheimer Disease",
        nct_number="NCT00000003",
        status="COMPLETED",
        conditions=["Alzheimer Disease"],
        interventions=["Amyloid antibody"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2025, 1, 1),
        source_url="https://clinicaltrials.gov/study/NCT00000003",
    )
    risk = PipelineRiskRecord(
        nct_number="NCT00000003",
        study_title="A Study in Alzheimer Disease",
        sponsor="Sponsor A",
        status="COMPLETED",
        intervention_category="amyloid antibody",
        timeline_signal="Low",
        timeline_evidence="Study first posted 2025-01-01; status COMPLETED; age 1.3 years.",
        competition_signal="High",
        competition_evidence="8 retained Alzheimer Disease studies share intervention category amyloid antibody.",
    )
    audit = SourceAudit(
        topic_url=profile.expert_topic_url,
        full_match_url=profile.expert_full_match_url,
        selected_condition_terms=profile.condition_terms,
        raw_count=3,
        retained_count=1,
        rejected_count=2,
        rejected_nct_numbers=["NCT_BAD_1", "NCT_BAD_2"],
    )

    package = DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )

    assert package.disease_profile.disease_name == "Alzheimer Disease"
    assert package.clinical_trials[0].status == "COMPLETED"
    assert package.source_audit.retained_count == 1


def test_disease_chapter_narratives_defaults_to_chinese_empty_strings():
    narratives = DiseaseChapterNarratives()

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""


def test_disease_chapter_narratives_accepts_english():
    narratives = DiseaseChapterNarratives(
        executive_summary="English executive summary.",
        clinical_trial_and_pipeline_landscape="English landscape summary.",
        pipeline_timeline_and_competition_risk="English risk summary.",
        language="en",
    )

    assert narratives.language == "en"
    assert narratives.executive_summary == "English executive summary."
