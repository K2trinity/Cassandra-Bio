from datetime import date

from src.reports.disease.landscape import (
    assign_landscape_strata,
    landscape_sort_key,
    stratum_counts,
)
from src.reports.disease.models import ClinicalTrialRecord


def _record(
    nct: str,
    *,
    phases: list[str],
    status: str,
    has_results: bool = False,
    posted: date | None = None,
) -> ClinicalTrialRecord:
    return ClinicalTrialRecord(
        study_title=f"Study {nct}",
        nct_number=nct,
        status=status,
        phases=phases,
        has_results=has_results,
        study_results="Results available" if has_results else "No posted results",
        conditions=["Alzheimer Disease"],
        interventions=["Drug A"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=posted,
        source_url=f"https://clinicaltrials.gov/study/{nct}",
    )


def test_assign_landscape_strata_uses_source_fields_only():
    evidence = assign_landscape_strata(
        _record(
            "NCT_EVIDENCE_FOUNDATION",
            phases=["PHASE3"],
            status="COMPLETED",
            has_results=True,
        )
    )
    frontier = assign_landscape_strata(
        _record("NCT_FRONTIER", phases=["PHASE1"], status="RECRUITING")
    )
    unclassified = assign_landscape_strata(
        _record("NCT_OBS", phases=["NA"], status="UNKNOWN")
    )

    assert evidence.strata == ["evidence", "foundation"]
    assert evidence.primary_stratum == "evidence"
    assert frontier.strata == ["frontier"]
    assert frontier.primary_stratum == "frontier"
    assert unclassified.strata == ["unclassified"]
    assert unclassified.primary_stratum == "unclassified"


def test_stratum_counts_count_each_membership_once():
    records = [
        assign_landscape_strata(
            _record("NCT_A", phases=["PHASE3"], status="COMPLETED", has_results=True)
        ),
        assign_landscape_strata(
            _record("NCT_B", phases=["PHASE2"], status="NOT_YET_RECRUITING")
        ),
    ]

    assert stratum_counts(records) == {
        "evidence": 1,
        "foundation": 1,
        "frontier": 1,
        "unclassified": 0,
    }


def test_landscape_sort_key_prioritizes_evidence_then_foundation_then_frontier():
    records = [
        assign_landscape_strata(
            _record(
                "NCT_FRONTIER",
                phases=["PHASE1"],
                status="RECRUITING",
                posted=date(2026, 1, 1),
            )
        ),
        assign_landscape_strata(
            _record(
                "NCT_FOUNDATION",
                phases=["PHASE4"],
                status="COMPLETED",
                posted=date(2024, 1, 1),
            )
        ),
        assign_landscape_strata(
            _record(
                "NCT_EVIDENCE",
                phases=["PHASE2"],
                status="COMPLETED",
                has_results=True,
                posted=date(2023, 1, 1),
            )
        ),
    ]

    sorted_records = sorted(records, key=landscape_sort_key)

    assert [record.nct_number for record in sorted_records] == [
        "NCT_EVIDENCE",
        "NCT_FOUNDATION",
        "NCT_FRONTIER",
    ]


def test_landscape_sort_key_uses_newest_available_source_date():
    records = [
        assign_landscape_strata(
            _record(
                "NCT_NEWEST_RESULTS",
                phases=["PHASE4"],
                status="COMPLETED",
                posted=date(2023, 1, 1),
            ).model_copy(
                update={
                    "last_update_posted": date(2024, 1, 1),
                    "results_first_posted": date(2026, 1, 1),
                }
            )
        ),
        assign_landscape_strata(
            _record(
                "NCT_INTERMEDIATE_UPDATE",
                phases=["PHASE4"],
                status="COMPLETED",
                posted=date(2023, 1, 1),
            ).model_copy(
                update={
                    "last_update_posted": date(2025, 1, 1),
                }
            )
        ),
    ]

    sorted_records = sorted(records, key=landscape_sort_key)

    assert [record.nct_number for record in sorted_records] == [
        "NCT_NEWEST_RESULTS",
        "NCT_INTERMEDIATE_UPDATE",
    ]
