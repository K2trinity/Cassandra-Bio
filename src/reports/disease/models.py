from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DiseaseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    target_type: Literal["disease", "company"] = "disease"
    company_name: str | None = None
    target_name: str | None = None
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
    why_stopped: str = ""
    phases: list[str] = Field(default_factory=list)
    has_results: bool = False
    study_results: str = "No posted results"
    results_url: str = ""
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: str = "Unknown"
    study_type: str = "Unknown"
    enrollment: int | None = None
    primary_outcome_measures: list[str] = Field(default_factory=list)
    secondary_outcome_measures: list[str] = Field(default_factory=list)
    study_first_posted: date | None = None
    results_first_posted: date | None = None
    last_update_posted: date | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    completion_date: date | None = None
    strata: list[str] = Field(default_factory=list)
    primary_stratum: str = "unclassified"
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


class DiseaseChapterNarratives(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = ""
    clinical_trial_and_pipeline_landscape: str = ""
    pipeline_timeline_and_competition_risk: str = ""
    disease_evidence_synthesis_summary: str = ""
    industry_landscape_summary: str = ""
    company_catalyst_and_rd_summary: str = ""
    language: Literal["zh", "en"] = "zh"


class DiseaseReportArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_content: str
    markdown_path: str | None = None
    html_path: str | None = None
    pdf_path: str | None = None
    ir_path: str | None = None
