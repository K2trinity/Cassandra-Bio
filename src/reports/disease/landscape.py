from __future__ import annotations

from datetime import date, timedelta

from .models import ClinicalTrialRecord

FOUNDATION_PHASES = {"PHASE3", "PHASE4"}
FOUNDATION_STATUSES = {"ACTIVE_NOT_RECRUITING", "COMPLETED"}
FRONTIER_PHASES = {"EARLY_PHASE1", "PHASE1", "PHASE2"}
FRONTIER_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING"}
STRATUM_PRIORITY = {
    "evidence": 0,
    "foundation": 1,
    "frontier": 2,
    "unclassified": 3,
}


def assign_landscape_strata(record: ClinicalTrialRecord) -> ClinicalTrialRecord:
    phases = {_clean_token(value) for value in record.phases}
    status = _clean_token(record.status)
    strata: list[str] = []

    if record.has_results:
        strata.append("evidence")
    if phases & FOUNDATION_PHASES and status in FOUNDATION_STATUSES:
        strata.append("foundation")
    if phases & FRONTIER_PHASES and status in FRONTIER_STATUSES:
        strata.append("frontier")
    if not strata:
        strata.append("unclassified")

    primary = sorted(strata, key=lambda value: STRATUM_PRIORITY.get(value, 99))[0]
    return record.model_copy(
        update={
            "strata": strata,
            "primary_stratum": primary,
        }
    )


def stratum_counts(records: list[ClinicalTrialRecord]) -> dict[str, int]:
    counts = {
        "evidence": 0,
        "foundation": 0,
        "frontier": 0,
        "unclassified": 0,
    }
    for record in records:
        memberships = record.strata or [record.primary_stratum or "unclassified"]
        for stratum in dict.fromkeys(memberships):
            if stratum in counts:
                counts[stratum] += 1
    return counts


def landscape_sort_key(record: ClinicalTrialRecord) -> tuple[int, int, timedelta, str]:
    primary = record.primary_stratum or "unclassified"
    priority = STRATUM_PRIORITY.get(primary, STRATUM_PRIORITY["unclassified"])
    has_results_rank = 0 if record.has_results else 1
    newest_date = max(
        (
            value
            for value in (
                record.last_update_posted,
                record.results_first_posted,
                record.study_first_posted,
            )
            if value is not None
        ),
        default=date.min,
    )
    return (priority, has_results_rank, date.max - newest_date, record.nct_number)


def _clean_token(value: str) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


__all__ = [
    "assign_landscape_strata",
    "landscape_sort_key",
    "stratum_counts",
]
