from datetime import date

from src.reports.disease.models import ClinicalTrialRecord, DiseaseProfile, PipelineRiskRecord
from src.reports.disease.package_builder import DiseaseReportPackageBuilder


def _profile() -> DiseaseProfile:
    return DiseaseProfile(
        query="Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease", "Alzheimer's Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D",
    )


def _trial(nct_number: str, posted: date | None, title: str | None = None) -> ClinicalTrialRecord:
    return ClinicalTrialRecord(
        study_title=title or f"Study {nct_number}",
        nct_number=nct_number,
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        interventions=["Drug A"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=posted,
        source_url=f"https://clinicaltrials.gov/study/{nct_number}",
    )


def _risk(nct_number: str) -> PipelineRiskRecord:
    return PipelineRiskRecord(
        nct_number=nct_number,
        study_title=f"Risk {nct_number}",
    )


def test_build_dedupes_sorts_newest_first_and_populates_audit():
    profile = _profile()
    risk_records = [_risk("NCT_NEW")]
    rejected_nct_numbers = ["NCT_REJECTED"]

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[
            _trial("NCT_OLD", date(2024, 1, 1)),
            _trial("NCT_NEW", date(2026, 1, 1)),
            _trial("NCT_OLD", date(2025, 1, 1), title="Duplicate old study"),
        ],
        raw_count="4",
        rejected_nct_numbers=rejected_nct_numbers,
        risk_records=risk_records,
    )

    assert [trial.nct_number for trial in package.clinical_trials] == ["NCT_NEW", "NCT_OLD"]
    assert package.clinical_trials[1].study_title == "Study NCT_OLD"
    assert package.risk_records == risk_records

    audit = package.source_audit
    assert audit.topic_url == profile.expert_topic_url
    assert audit.full_match_url == profile.expert_full_match_url
    assert audit.selected_condition_terms == profile.condition_terms
    assert audit.raw_count == 4
    assert audit.retained_count == 2
    assert audit.rejected_count == 1
    assert audit.rejected_nct_numbers == ["NCT_REJECTED"]
    assert audit.rejected_nct_numbers is not rejected_nct_numbers


def test_build_caps_retained_trials_to_max_records():
    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[
            _trial(f"NCT{i:08d}", date(2026, 1, 1)) for i in range(55)
        ],
        raw_count=55,
        rejected_nct_numbers=[],
        risk_records=[],
        max_records=50,
    )

    assert len(package.clinical_trials) == 50
    assert package.source_audit.retained_count == 50


def test_build_sorts_missing_study_first_posted_last():
    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[
            _trial("NCT_MISSING", None),
            _trial("NCT_NEW", date(2026, 1, 1)),
            _trial("NCT_OLD", date(2024, 1, 1)),
        ],
        raw_count=3,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    assert [trial.nct_number for trial in package.clinical_trials] == [
        "NCT_NEW",
        "NCT_OLD",
        "NCT_MISSING",
    ]
