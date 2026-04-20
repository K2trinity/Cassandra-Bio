"""Pydantic models for the objective biomedical analysis report engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceDocument(BaseModel):
    """Traceable fact source used by the report prompt."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["SEC", "PATENT", "PUBMED", "CLINICALTRIAL", "OTHER"]
    identifier: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    excerpt: str = Field(..., min_length=1)
    url: Optional[str] = None


class DiseaseProfile(BaseModel):
    """Disease-level framing used by disease-oriented reports."""

    model_config = ConfigDict(extra="forbid")

    disease_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    burden_summary: str = Field(..., min_length=1)
    unmet_need_summary: str = Field(..., min_length=1)
    source_documents: List[SourceDocument] = Field(default_factory=list)


class PipelineIndication(BaseModel):
    """One indication mapped to one development stage."""

    model_config = ConfigDict(extra="forbid")

    indication: str = Field(..., min_length=1)
    clinical_phase: str = Field(..., min_length=1)
    status: Optional[str] = Field(default=None, description="Development or enrollment status")
    evidence_note: Optional[str] = Field(default=None, description="Short factual note from source material")


class PipelineData(BaseModel):
    """Drug pipeline and mechanism of action facts."""

    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    moa_description: str = Field(..., min_length=1)
    target_description: str = Field(..., min_length=1)
    indications: List[PipelineIndication] = Field(default_factory=list)
    development_stage: Optional[str] = Field(default=None, description="Overall development stage")
    source_documents: List[SourceDocument] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    """Company and organizational facts."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1)
    management_summary: str = Field(..., min_length=1)
    scientist_summary: str = Field(..., min_length=1)
    cash_runway_months: Optional[float] = Field(default=None, description="Estimated runway in months")
    rd_spend_ratio: Optional[float] = Field(default=None, description="R&D spending as a fraction of total operating spend")
    source_documents: List[SourceDocument] = Field(default_factory=list)

    @field_validator("cash_runway_months")
    @classmethod
    def _validate_cash_runway(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("cash_runway_months must be non-negative")
        return value

    @field_validator("rd_spend_ratio")
    @classmethod
    def _validate_rd_spend_ratio(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not 0 <= value <= 1:
            raise ValueError("rd_spend_ratio must be between 0 and 1")
        return value


class CompetitorAsset(BaseModel):
    """One competitor in the same target or indication area."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1)
    asset_name: str = Field(..., min_length=1)
    mechanism: Optional[str] = None
    development_stage: Optional[str] = None
    differentiation_note: Optional[str] = None
    source_documents: List[SourceDocument] = Field(default_factory=list)


class CompetitiveLandscape(BaseModel):
    """Target-level competitive landscape."""

    model_config = ConfigDict(extra="forbid")

    target_area: str = Field(..., min_length=1)
    competitors: List[CompetitorAsset] = Field(default_factory=list)
    source_documents: List[SourceDocument] = Field(default_factory=list)


class PubMedRecord(BaseModel):
    """Verified literature fact from PubMed or PMC."""

    model_config = ConfigDict(extra="forbid")

    pmid: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    finding_summary: str = Field(..., min_length=1)
    safety_relevance: Optional[str] = None
    url: Optional[str] = None


class ClinicalTrialRecord(BaseModel):
    """Verified trial fact from ClinicalTrials.gov or equivalent registry."""

    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    phase: Optional[str] = None
    result_summary: str = Field(..., min_length=1)
    safety_summary: Optional[str] = None
    url: Optional[str] = None


class TrialDataFieldRecord(BaseModel):
    """Field-level trial matrix entry for disease-oriented asset comparison."""

    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    asset_name: Optional[str] = None
    sponsor: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    enrollment: Optional[str] = None
    study_design: Optional[str] = None
    primary_endpoint: Optional[str] = None
    secondary_endpoint: Optional[str] = None
    orr: Optional[str] = None
    pfs: Optional[str] = None
    os: Optional[str] = None
    grade3plus_ae: Optional[str] = None
    sae: Optional[str] = None
    discontinuation: Optional[str] = None
    source_documents: List[SourceDocument] = Field(default_factory=list)


class DrugAssetEntry(BaseModel):
    """Drug-level entry for disease catalog output."""

    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    modality_or_scaffold: str = Field(..., min_length=1)
    molecular_targets: List[str] = Field(default_factory=list)
    sponsor_company: str = Field(..., min_length=1)
    company_overview: Optional[str] = None
    development_stage: Optional[str] = None
    clinical_status: Optional[str] = None
    indication_subtype: Optional[str] = None
    trial_ids: List[str] = Field(default_factory=list)
    source_documents: List[SourceDocument] = Field(default_factory=list)


class SafetySignal(BaseModel):
    """A factual safety signal extracted from evidence."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["PUBMED", "CLINICALTRIAL", "SEC", "PATENT", "OTHER"]
    source_id: str = Field(..., min_length=1)
    signal_type: str = Field(..., min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    quote: str = Field(..., min_length=1)
    interpretation: Optional[str] = None


class ClinicalEvidence(BaseModel):
    """Verified clinical evidence and safety signals."""

    model_config = ConfigDict(extra="forbid")

    pubmed_records: List[PubMedRecord] = Field(default_factory=list)
    clinical_trial_records: List[ClinicalTrialRecord] = Field(default_factory=list)
    safety_signals: List[SafetySignal] = Field(default_factory=list)
    source_documents: List[SourceDocument] = Field(default_factory=list)


class DueDiligenceState(BaseModel):
    """Validated input state for the neutral biomedical report generator."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_query: str = Field(..., min_length=1)
    disease_profile: Optional[DiseaseProfile] = None
    drug_catalog: List[DrugAssetEntry] = Field(default_factory=list)
    trial_data_matrix: List[TrialDataFieldRecord] = Field(default_factory=list)
    pipeline: PipelineData
    company_profile: CompanyProfile
    competitive_landscape: CompetitiveLandscape
    clinical_evidence: ClinicalEvidence
    source_documents: List[SourceDocument] = Field(default_factory=list)
    report_title: str = Field(default="Objective Biomedical Research Analysis Report")
    report_language: Literal["zh-CN", "en-US"] = Field(default="zh-CN")
    analysis_mode: Literal["disease-oriented", "asset-oriented"] = Field(default="disease-oriented")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_prompt_payload(self) -> Dict[str, Any]:
        """Return a prompt-safe JSON payload."""

        return self.model_dump(mode="json")