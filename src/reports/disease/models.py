from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiseaseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    disease_name: str = Field(..., min_length=1)
    canonical_condition: str = Field(..., min_length=1)
    condition_terms: list[str] = Field(default_factory=list)
    normalized_terms: list[str] = Field(default_factory=list)
    expert_topic_url: str = Field(..., min_length=1)
    expert_full_match_url: str = Field(..., min_length=1)


class ClinicalTrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_title: str = Field(..., min_length=1)
    nct_number: str = Field(..., min_length=1)
    status: str = Field(default="Unknown", min_length=1)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: str = "Unknown"
    study_type: str = "Unknown"
    study_first_posted: date | None = None
    last_update_posted: date | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    completion_date: date | None = None
    source_url: str = Field(..., min_length=1)


class PipelineRiskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_number: str = Field(..., min_length=1)
    study_title: str = Field(..., min_length=1)
    sponsor: str = ""
    status: str = ""
    intervention_category: str = ""
    timeline_signal: str = "Data insufficient"
    timeline_evidence: str = ""
    competition_signal: str = "Data insufficient"
    competition_evidence: str = ""


class SourceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_url: str = ""
    full_match_url: str = ""
    selected_condition_terms: list[str] = Field(default_factory=list)
    raw_count: int = 0
    retained_count: int = 0
    rejected_count: int = 0
    rejected_nct_numbers: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class DiseaseReportPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_profile: DiseaseProfile
    clinical_trials: list[ClinicalTrialRecord] = Field(default_factory=list)
    risk_records: list[PipelineRiskRecord] = Field(default_factory=list)
    source_audit: SourceAudit
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiseaseReportArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_content: str
    markdown_path: str | None = None
    html_path: str | None = None
    pdf_path: str | None = None
    ir_path: str | None = None
