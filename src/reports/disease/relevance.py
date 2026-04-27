from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .condition_matcher import conditions_full_match
from .models import ClinicalTrialRecord, DiseaseProfile


class RelevanceGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained: list[ClinicalTrialRecord] = Field(default_factory=list)
    rejected_nct_numbers: list[str] = Field(default_factory=list)


class DiseaseRelevanceGate:
    def filter_records(self, records: list[ClinicalTrialRecord], profile: DiseaseProfile) -> RelevanceGateResult:
        retained: list[ClinicalTrialRecord] = []
        first_seen_order: list[str] = []
        rejected_candidates: set[str] = set()
        retained_nct_numbers: set[str] = set()
        for record in records:
            if record.nct_number not in rejected_candidates and record.nct_number not in retained_nct_numbers:
                first_seen_order.append(record.nct_number)
            if conditions_full_match(record.conditions, profile):
                if record.nct_number in retained_nct_numbers:
                    continue
                retained.append(record)
                retained_nct_numbers.add(record.nct_number)
                rejected_candidates.discard(record.nct_number)
            else:
                if record.nct_number not in retained_nct_numbers:
                    rejected_candidates.add(record.nct_number)
        rejected = [nct_number for nct_number in first_seen_order if nct_number in rejected_candidates]
        return RelevanceGateResult(retained=retained, rejected_nct_numbers=rejected)
