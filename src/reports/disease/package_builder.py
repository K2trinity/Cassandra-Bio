from __future__ import annotations

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
            risk_records=risk_records,
            source_audit=audit,
        )
