from __future__ import annotations

from collections import Counter

from .landscape import landscape_sort_key, stratum_counts
from .models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


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
            if existing is None or landscape_sort_key(record) < landscape_sort_key(existing):
                deduped_by_nct[record.nct_number] = record

        sorted_records = sorted(
            deduped_by_nct.values(),
            key=landscape_sort_key,
        )
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
            details={
                "stratum_counts": stratum_counts(capped_records),
            },
        )

        return DiseaseReportPackage(
            disease_profile=disease_profile,
            clinical_trials=capped_records,
            risk_records=aligned_risk_records,
            source_audit=audit,
        )


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
