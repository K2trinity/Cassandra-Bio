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
        rejected: list[str] = []
        seen: set[str] = set()
        for record in records:
            if record.nct_number in seen:
                continue
            seen.add(record.nct_number)
            if conditions_full_match(record.conditions, profile):
                retained.append(record)
            else:
                rejected.append(record.nct_number)
        return RelevanceGateResult(retained=retained, rejected_nct_numbers=rejected)
