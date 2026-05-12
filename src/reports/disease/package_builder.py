from __future__ import annotations

from collections import Counter
from datetime import date

from .landscape import landscape_sort_key, stratum_counts as disease_stratum_counts
from .models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


COMPANY_STRATUM_ORDER = {
    "catalyst": 0,
    "expansion": 1,
    "track_record": 2,
    "unclassified": 3,
}


class DiseaseReportPackageBuilder:
    @staticmethod
    def build(
        *,
        disease_profile: DiseaseProfile,
        retained_records: list[ClinicalTrialRecord],
        raw_count: int,
        rejected_nct_numbers: list[str],
        risk_records: list[PipelineRiskRecord],
        max_records: int = 50,
    ) -> DiseaseReportPackage:
        deduped_by_nct: dict[str, ClinicalTrialRecord] = {}
        for record in retained_records:
            existing = deduped_by_nct.get(record.nct_number)
            candidate = _merge_duplicate_record(
                disease_profile,
                existing,
                record,
            )
            deduped_by_nct[record.nct_number] = candidate

        sorted_records = _sort_records(disease_profile, list(deduped_by_nct.values()))
        capped_records = sorted_records[:max_records]
        aligned_risk_records = _align_risk_records_to_trials(risk_records, capped_records)
        aligned_risk_records = _refresh_competition_evidence(
            risk_records=aligned_risk_records,
            disease_name=disease_profile.disease_name,
        )

        audit = SourceAudit(
            topic_url=disease_profile.expert_topic_url,
            full_match_url=disease_profile.expert_full_match_url,
            selected_condition_terms=list(disease_profile.condition_terms),
            raw_count=int(raw_count),
            retained_count=len(capped_records),
            rejected_count=len(rejected_nct_numbers),
            rejected_nct_numbers=list(rejected_nct_numbers),
            details=_audit_details(disease_profile, capped_records),
        )

        return DiseaseReportPackage(
            disease_profile=disease_profile,
            clinical_trials=capped_records,
            risk_records=aligned_risk_records,
            source_audit=audit,
        )


def _merge_duplicate_record(
    disease_profile: DiseaseProfile,
    existing: ClinicalTrialRecord | None,
    record: ClinicalTrialRecord,
) -> ClinicalTrialRecord:
    if existing is None:
        return record

    key = _record_sort_key(disease_profile)
    selected = record if key(record) < key(existing) else existing
    strata = _unique_values([*existing.strata, *record.strata])
    if not strata:
        strata = _unique_values([existing.primary_stratum, record.primary_stratum]) or ["unclassified"]
    primary = _primary_stratum(disease_profile, strata)
    return selected.model_copy(
        update={
            "strata": strata,
            "primary_stratum": primary,
        }
    )


def _record_sort_key(disease_profile: DiseaseProfile):
    if disease_profile.target_type == "company":
        return _company_sort_key
    return landscape_sort_key


def _sort_records(
    disease_profile: DiseaseProfile,
    records: list[ClinicalTrialRecord],
) -> list[ClinicalTrialRecord]:
    return sorted(records, key=_record_sort_key(disease_profile))


def _audit_details(
    disease_profile: DiseaseProfile,
    records: list[ClinicalTrialRecord],
) -> dict[str, object]:
    details: dict[str, object] = {"target_type": disease_profile.target_type}
    if disease_profile.target_name:
        details["target_name"] = disease_profile.target_name
    if disease_profile.company_name:
        details["company_name"] = disease_profile.company_name
    if disease_profile.sponsor_query and disease_profile.sponsor_query != disease_profile.company_name:
        details["sponsor_query"] = disease_profile.sponsor_query

    if disease_profile.target_type == "company":
        counts = _generic_stratum_counts(records)
    else:
        counts = disease_stratum_counts(records)
    if counts:
        details["stratum_counts"] = counts

    if disease_profile.target_type == "company":
        expansion_condition_counts = _condition_counts_for_stratum(records, "expansion")
        if expansion_condition_counts:
            details["expansion_condition_counts"] = expansion_condition_counts

    return details


def _align_risk_records_to_trials(
    risk_records: list[PipelineRiskRecord],
    trials: list[ClinicalTrialRecord],
) -> list[PipelineRiskRecord]:
    risks_by_nct: dict[str, list[PipelineRiskRecord]] = {}
    for record in risk_records:
        risks_by_nct.setdefault(record.nct_number, []).append(record)

    aligned: list[PipelineRiskRecord] = []
    for trial in trials:
        candidates = risks_by_nct.get(trial.nct_number, [])
        if not candidates:
            continue
        title_match = next(
            (record for record in candidates if record.study_title == trial.study_title),
            None,
        )
        aligned.append(title_match or candidates[0])
    return aligned


def _refresh_competition_evidence(
    *,
    risk_records: list[PipelineRiskRecord],
    disease_name: str,
) -> list[PipelineRiskRecord]:
    category_counts = Counter(
        record.intervention_category
        for record in risk_records
        if record.intervention_category
    )
    return [
        record.model_copy(
            update={
                "competition_signal": _competition_signal(
                    category=record.intervention_category,
                    category_count=category_counts.get(record.intervention_category, 0),
                ),
                "competition_evidence": _competition_evidence(
                    category=record.intervention_category,
                    category_count=category_counts.get(record.intervention_category, 0),
                    disease_name=disease_name,
                ),
            }
        )
        for record in risk_records
    ]


def _competition_signal(*, category: str, category_count: int) -> str:
    if not category:
        return "Data insufficient"
    if category_count >= 8:
        return "High"
    if 3 <= category_count <= 7:
        return "Medium"
    return "Low"


def _competition_evidence(*, category: str, category_count: int, disease_name: str) -> str:
    if not category:
        return f"No intervention category available for {disease_name}."
    return (
        f"{category_count} retained {disease_name} studies share "
        f"intervention category {category}."
    )


def _company_sort_key(record: ClinicalTrialRecord) -> tuple[object, ...]:
    stratum = _report_stratum(record)
    rank = COMPANY_STRATUM_ORDER.get(stratum, COMPANY_STRATUM_ORDER["unclassified"])
    if stratum == "catalyst":
        date_key = _ascending_date_key(
            record.primary_completion_date
            or record.completion_date
            or record.study_first_posted
        )
    elif stratum == "expansion":
        date_key = _descending_date_key(record.study_first_posted)
    elif stratum == "track_record":
        date_key = _descending_date_key(
            record.last_update_posted
            or record.results_first_posted
            or record.study_first_posted
        )
    else:
        date_key = _descending_date_key(record.study_first_posted)
    return (rank, *date_key, record.nct_number)


def _report_stratum(record: ClinicalTrialRecord) -> str:
    return _primary_stratum("company", [record.primary_stratum, *record.strata])


def _primary_stratum(
    disease_profile: DiseaseProfile | str,
    strata: list[str],
) -> str:
    target_type = disease_profile if isinstance(disease_profile, str) else disease_profile.target_type
    priority = COMPANY_STRATUM_ORDER if target_type == "company" else {
        "evidence": 0,
        "foundation": 1,
        "frontier": 2,
        "unclassified": 3,
    }
    candidates = [stratum for stratum in strata if stratum]
    if not candidates:
        return "unclassified"
    return sorted(candidates, key=lambda value: priority.get(value, 99))[0]


def _ascending_date_key(value: date | None) -> tuple[bool, int]:
    return (value is None, value.toordinal() if value else 0)


def _descending_date_key(value: date | None) -> tuple[bool, int]:
    return (value is None, -value.toordinal() if value else 0)


def _condition_counts_for_stratum(
    records: list[ClinicalTrialRecord],
    stratum: str,
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        strata = record.strata or [record.primary_stratum or "unclassified"]
        if stratum not in strata:
            continue
        counter.update(condition for condition in record.conditions if condition)
    return {
        condition: count
        for condition, count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )
    }


def _generic_stratum_counts(records: list[ClinicalTrialRecord]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        strata = record.strata or [record.primary_stratum or "unclassified"]
        counter.update(stratum for stratum in strata if stratum)
    return dict(counter)


def _unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique
