from __future__ import annotations

from datetime import date

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
            deduped_by_nct.setdefault(record.nct_number, record)

        sorted_records = sorted(
            deduped_by_nct.values(),
            key=lambda record: (
                record.study_first_posted is not None,
                record.study_first_posted or date.min,
            ),
            reverse=True,
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
        )

        return DiseaseReportPackage(
            disease_profile=disease_profile,
            clinical_trials=capped_records,
            risk_records=risk_records,
            source_audit=audit,
        )
