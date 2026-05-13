from datetime import date

from src.reports.disease.models import ClinicalTrialRecord, DiseaseProfile, PipelineRiskRecord
from src.reports.disease.package_builder import DiseaseReportPackageBuilder


def _profile(
    *,
    target_type: str = "disease",
    target_name: str | None = None,
    company_name: str | None = None,
) -> DiseaseProfile:
    return DiseaseProfile(
        query="Alzheimer disease",
        target_type=target_type,
        target_name=target_name,
        company_name=company_name,
        disease_name="Alzheimer Disease" if target_type == "disease" else target_name or company_name or "Company",
        canonical_condition="Alzheimer Disease" if target_type == "disease" else target_name or company_name or "Company",
        condition_terms=["Alzheimer Disease", "Alzheimer's Disease"] if target_type == "disease" else [],
        normalized_terms=["alzheimer disease"] if target_type == "disease" else [],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D",
    )


def _trial(
    nct_number: str,
    posted: date | None,
    title: str | None = None,
    *,
    status: str = "RECRUITING",
    conditions: list[str] | None = None,
    phases: list[str] | None = None,
    has_results: bool = False,
    strata: list[str] | None = None,
    primary_stratum: str = "unclassified",
    primary_completion_date: date | None = None,
    results_first_posted: date | None = None,
    last_update_posted: date | None = None,
) -> ClinicalTrialRecord:
    return ClinicalTrialRecord(
        study_title=title or f"Study {nct_number}",
        nct_number=nct_number,
        status=status,
        phases=phases or ["PHASE1"],
        has_results=has_results,
        conditions=conditions or ["Alzheimer Disease"],
        interventions=["Drug A"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=posted,
        results_first_posted=results_first_posted,
        last_update_posted=last_update_posted,
        primary_completion_date=primary_completion_date,
        strata=strata or [],
        primary_stratum=primary_stratum,
        source_url=f"https://clinicaltrials.gov/study/{nct_number}",
    )


def _risk(nct_number: str, title: str | None = None, category: str = "") -> PipelineRiskRecord:
    return PipelineRiskRecord(
        nct_number=nct_number,
        study_title=title or f"Risk {nct_number}",
        intervention_category=category,
    )


def test_build_dedupes_sorts_by_disease_landscape_priority_and_populates_audit():
    evidence = _trial(
        "NCT_EVIDENCE",
        date(2024, 1, 1),
        has_results=True,
        strata=["evidence", "foundation"],
        primary_stratum="evidence",
        results_first_posted=date(2026, 2, 1),
        last_update_posted=date(2026, 3, 1),
    )
    foundation = _trial(
        "NCT_FOUNDATION",
        date(2026, 1, 1),
        phases=["PHASE3"],
        strata=["foundation"],
        primary_stratum="foundation",
    )
    frontier = _trial(
        "NCT_FRONTIER",
        date(2026, 5, 1),
        phases=["PHASE1"],
        strata=["frontier"],
        primary_stratum="frontier",
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[frontier, foundation, evidence],
        raw_count="4",
        rejected_nct_numbers=["NCT_REJECTED"],
        risk_records=[_risk("NCT_EVIDENCE")],
    )

    assert [trial.nct_number for trial in package.clinical_trials] == [
        "NCT_EVIDENCE",
        "NCT_FOUNDATION",
        "NCT_FRONTIER",
    ]
    assert package.source_audit.raw_count == 4
    assert package.source_audit.retained_count == 3
    assert package.source_audit.rejected_nct_numbers == ["NCT_REJECTED"]
    assert package.source_audit.details["target_type"] == "disease"
    assert package.source_audit.details["stratum_counts"] == {
        "evidence": 1,
        "foundation": 2,
        "frontier": 1,
        "unclassified": 0,
    }


def test_build_keeps_best_duplicate_and_merges_strata():
    old_frontier = _trial(
        "NCT_DUP",
        date(2023, 1, 1),
        title="Frontier old",
        strata=["frontier"],
        primary_stratum="frontier",
    )
    new_evidence = _trial(
        "NCT_DUP",
        date(2026, 1, 1),
        title="Evidence new",
        has_results=True,
        strata=["evidence", "foundation"],
        primary_stratum="evidence",
        results_first_posted=date(2026, 2, 1),
        last_update_posted=date(2026, 3, 1),
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[old_frontier, new_evidence],
        raw_count=2,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    retained = package.clinical_trials[0]
    assert retained.study_title == "Evidence new"
    assert retained.primary_stratum == "evidence"
    assert retained.strata == ["frontier", "evidence", "foundation"]
    assert package.source_audit.details["stratum_counts"] == {
        "evidence": 1,
        "foundation": 1,
        "frontier": 1,
        "unclassified": 0,
    }


def test_build_aligns_duplicate_risk_records_to_selected_clinical_record():
    stale_frontier = _trial("NCT_DUP_RISK", date(2023, 1, 1), title="Stale frontier trial")
    better_evidence = _trial(
        "NCT_DUP_RISK",
        date(2026, 1, 1),
        title="Better evidence trial",
        has_results=True,
        strata=["evidence", "foundation"],
        primary_stratum="evidence",
        results_first_posted=date(2026, 2, 1),
    )
    stale_risk = _risk("NCT_DUP_RISK", title="Stale frontier trial")
    better_risk = _risk("NCT_DUP_RISK", title="Better evidence trial")

    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[stale_frontier, better_evidence],
        raw_count=2,
        rejected_nct_numbers=[],
        risk_records=[stale_risk, better_risk],
    )

    assert [trial.study_title for trial in package.clinical_trials] == ["Better evidence trial"]
    assert package.risk_records == [
        better_risk.model_copy(
            update={"competition_evidence": "No intervention category available for Alzheimer Disease."}
        )
    ]


def test_build_drops_risk_records_for_capped_out_clinical_trials():
    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[
            _trial("NCT_KEEP", date(2026, 1, 1), title="Kept trial", strata=["frontier"], primary_stratum="frontier"),
            _trial("NCT_DROP", date(2025, 1, 1), title="Capped out trial", strata=["frontier"], primary_stratum="frontier"),
        ],
        raw_count=2,
        rejected_nct_numbers=[],
        risk_records=[
            _risk("NCT_KEEP", title="Kept trial"),
            _risk("NCT_DROP", title="Capped out trial"),
        ],
        max_records=1,
    )

    assert [trial.nct_number for trial in package.clinical_trials] == ["NCT_KEEP"]
    assert [record.nct_number for record in package.risk_records] == ["NCT_KEEP"]


def test_build_recomputes_competition_evidence_after_final_cap():
    retained_risks = [
        PipelineRiskRecord(
            nct_number="NCT_KEEP",
            study_title="Kept amyloid antibody trial",
            intervention_category="amyloid antibody",
            timeline_signal="Low",
            timeline_evidence="Kept timeline evidence.",
        ),
        PipelineRiskRecord(
            nct_number="NCT_DROP",
            study_title="Dropped amyloid antibody trial",
            intervention_category="amyloid antibody",
            timeline_signal="Medium",
            timeline_evidence="Dropped timeline evidence.",
        ),
    ]

    package = DiseaseReportPackageBuilder().build(
        disease_profile=_profile(),
        retained_records=[
            _trial("NCT_KEEP", date(2026, 1, 1), title="Kept amyloid antibody trial", strata=["frontier"], primary_stratum="frontier"),
            _trial("NCT_DROP", date(2025, 1, 1), title="Dropped amyloid antibody trial", strata=["frontier"], primary_stratum="frontier"),
        ],
        raw_count=2,
        rejected_nct_numbers=[],
        risk_records=retained_risks,
        max_records=1,
    )

    assert [record.nct_number for record in package.risk_records] == ["NCT_KEEP"]
    retained_risk = package.risk_records[0]
    assert retained_risk.timeline_signal == "Low"
    assert retained_risk.timeline_evidence == "Kept timeline evidence."
    assert retained_risk.competition_signal == "Low"
    assert (
        retained_risk.competition_evidence
        == "1 retained Alzheimer Disease studies share intervention category amyloid antibody."
    )


def test_build_populates_company_target_metadata_and_stratum_counts():
    profile = _profile(
        target_type="company",
        target_name="Vertex Pharmaceuticals",
        company_name="Vertex Pharmaceuticals",
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[
            _trial(
                "NCT_CATALYST",
                date(2026, 1, 1),
                conditions=["Sickle Cell Disease"],
                strata=["catalyst", "track_record"],
                primary_stratum="catalyst",
            ),
            _trial(
                "NCT_EXPANSION",
                date(2025, 1, 1),
                conditions=["Alzheimer Disease"],
                strata=["expansion"],
                primary_stratum="expansion",
            ),
            _trial(
                "NCT_UNCLASSIFIED",
                date(2024, 1, 1),
                primary_stratum="unclassified",
            ),
        ],
        raw_count=3,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    assert package.source_audit.details == {
        "target_type": "company",
        "target_name": "Vertex Pharmaceuticals",
        "company_name": "Vertex Pharmaceuticals",
        "stratum_counts": {
            "catalyst": 1,
            "track_record": 1,
            "expansion": 2,
        },
        "expansion_condition_counts": {
            "Alzheimer Disease": 2,
        },
    }


def test_build_classifies_company_broad_portfolio_records_without_unclassified_bucket():
    profile = _profile(
        target_type="company",
        target_name="Moderna, Inc.",
        company_name="Moderna, Inc.",
    )
    portfolio_baseline = _trial(
        "NCT_BASELINE",
        date(2024, 1, 1),
        status="UNKNOWN",
        phases=[],
        primary_stratum="unclassified",
    ).model_copy(update={"phases": [], "study_type": "OBSERVATIONAL"})

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[
            _trial(
                "NCT_CATALYST",
                date(2025, 1, 1),
                status="ACTIVE_NOT_RECRUITING",
                phases=["PHASE3"],
                primary_completion_date=date(2026, 9, 1),
            ),
            _trial(
                "NCT_EXPANSION",
                date(2025, 2, 1),
                status="RECRUITING",
                phases=["PHASE1"],
            ),
            _trial(
                "NCT_TRACK",
                date(2023, 1, 1),
                status="COMPLETED",
                phases=[],
                has_results=True,
            ).model_copy(update={"phases": []}),
            portfolio_baseline,
        ],
        raw_count=4,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    assert package.source_audit.details["stratum_counts"] == {
        "catalyst": 1,
        "expansion": 1,
        "track_record": 1,
        "portfolio_baseline": 1,
    }
    assert "unclassified" not in package.source_audit.details["stratum_counts"]
    assert {
        trial.nct_number: trial.primary_stratum
        for trial in package.clinical_trials
    } == {
        "NCT_CATALYST": "catalyst",
        "NCT_EXPANSION": "expansion",
        "NCT_TRACK": "track_record",
        "NCT_BASELINE": "portfolio_baseline",
    }


def test_build_orders_company_records_by_stratum_specific_dates():
    profile = _profile(
        target_type="company",
        target_name="Vertex Pharmaceuticals",
        company_name="Vertex Pharmaceuticals",
    )

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[
            _trial(
                "NCT_EXPANSION_NEW",
                date(2026, 5, 1),
                conditions=["Acute Pain"],
                strata=["expansion"],
                primary_stratum="expansion",
            ),
            _trial(
                "NCT_CATALYST_LATER",
                date(2026, 4, 1),
                conditions=["Sickle Cell Disease"],
                strata=["catalyst"],
                primary_stratum="catalyst",
                primary_completion_date=date(2026, 12, 1),
            ),
            _trial(
                "NCT_TRACK_RECENT",
                date(2023, 1, 1),
                conditions=["Cystic Fibrosis"],
                strata=["track_record"],
                primary_stratum="track_record",
                last_update_posted=date(2026, 6, 1),
            ),
            _trial(
                "NCT_CATALYST_SOON",
                date(2024, 1, 1),
                conditions=["Beta Thalassemia"],
                strata=["catalyst"],
                primary_stratum="catalyst",
                primary_completion_date=date(2026, 6, 1),
            ),
        ],
        raw_count=4,
        rejected_nct_numbers=[],
        risk_records=[],
    )

    assert [trial.nct_number for trial in package.clinical_trials] == [
        "NCT_CATALYST_SOON",
        "NCT_CATALYST_LATER",
        "NCT_EXPANSION_NEW",
        "NCT_TRACK_RECENT",
    ]
    assert package.source_audit.details["expansion_condition_counts"] == {
        "Acute Pain": 1,
    }
