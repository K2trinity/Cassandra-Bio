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
        phases=["PHASE1"],
        conditions=["Alzheimer Disease"],
        interventions=["Drug A"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=posted,
        strata=["frontier"],
        primary_stratum="frontier",
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
            _trial("NCT_OLD", date(2025, 1, 1), title="Newer duplicate old study"),
        ],
        raw_count="4",
        rejected_nct_numbers=rejected_nct_numbers,
        risk_records=risk_records,
    )

    assert [trial.nct_number for trial in package.clinical_trials] == ["NCT_NEW", "NCT_OLD"]
    assert package.clinical_trials[1].study_title == "Newer duplicate old study"
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


def test_build_sorts_by_landscape_priority_and_records_stratum_counts():
    profile = _profile()
    evidence = _trial("NCT_EVIDENCE", date(2024, 1, 1))
    evidence = evidence.model_copy(
        update={
            "has_results": True,
            "strata": ["evidence", "foundation"],
            "primary_stratum": "evidence",
        }
    )
    foundation = _trial("NCT_FOUNDATION", date(2026, 1, 1)).model_copy(
        update={"strata": ["foundation"], "primary_stratum": "foundation"}
    )
    frontier = _trial("NCT_FRONTIER", date(2026, 5, 1)).model_copy(
        update={"strata": ["frontier"], "primary_stratum": "frontier"}
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[frontier, foundation, evidence],
        raw_count=3,
        rejected_nct_numbers=[],
        risk_records=[],
        max_records=50,
    )

    assert [trial.nct_number for trial in package.clinical_trials] == [
        "NCT_EVIDENCE",
        "NCT_FOUNDATION",
        "NCT_FRONTIER",
    ]
    assert package.source_audit.details["stratum_counts"] == {
        "evidence": 1,
        "foundation": 2,
        "frontier": 1,
        "unclassified": 0,
    }


def test_build_keeps_best_duplicate_by_landscape_sort_key():
    old_frontier = _trial("NCT_DUP", date(2023, 1, 1), title="Frontier old")
    new_evidence = _trial("NCT_DUP", date(2026, 1, 1), title="Evidence new").model_copy(
        update={
            "has_results": True,
            "strata": ["evidence", "foundation"],
            "primary_stratum": "evidence",
            "results_first_posted": date(2026, 2, 1),
            "last_update_posted": date(2026, 3, 1),
        }
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[old_frontier, new_evidence],
        raw_count=2,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    assert [trial.nct_number for trial in package.clinical_trials] == ["NCT_DUP"]
    retained = package.clinical_trials[0]
    assert retained.study_title == "Evidence new"
    assert retained.has_results is True
    assert retained.primary_stratum == "evidence"
    assert retained.strata == ["evidence", "foundation"]
    assert retained.results_first_posted == date(2026, 2, 1)
    assert retained.last_update_posted == date(2026, 3, 1)
    assert package.source_audit.details["stratum_counts"] == {
        "evidence": 1,
        "foundation": 1,
        "frontier": 0,
        "unclassified": 0,
    }
