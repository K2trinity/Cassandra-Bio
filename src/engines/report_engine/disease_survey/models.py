# src/engines/report_engine/disease_survey/models.py
"""Pydantic models for the disease survey report module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DrugAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    modality: str = ""
    targets: List[str] = Field(default_factory=list)
    sponsor: str = ""
    phase: Optional[str] = None
    status: Optional[str] = None
    trial_ids: List[str] = Field(default_factory=list)
    indication_subtype: Optional[str] = None


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    asset_name: Optional[str] = None
    sponsor: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    enrollment: Optional[str] = None
    primary_endpoint: Optional[str] = None
    secondary_endpoint: Optional[str] = None
    ae_grade3plus: Optional[str] = None
    sae: Optional[str] = None


class SponsorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1)
    pipeline_count: int = 0
    lead_phase: Optional[str] = None
    ticker: Optional[str] = None
    market_cap: Optional[float] = None
    cash_runway_months: Optional[float] = None
    rd_ratio: Optional[float] = None


class CNSBenchmarkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_name: str = Field(..., min_length=1)
    publication_count_5yr: int = 0
    trial_count_5yr: int = 0
    top_journal_citations: int = 0
    trend: str = "stable"
    matched: bool = False


class LiteratureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pmid: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    journal: Optional[str] = None
    year: Optional[int] = None
    authors: Optional[str] = None
    doi: Optional[str] = None
    relevance_tag: Optional[str] = None


class DiseaseSurveyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    drug_assets: List[DrugAsset] = Field(default_factory=list)
    trials: List[TrialRecord] = Field(default_factory=list)
    sponsors: List[SponsorProfile] = Field(default_factory=list)
    literature: List[LiteratureRecord] = Field(default_factory=list)
    cns_benchmark: List[CNSBenchmarkEntry] = Field(default_factory=list)
    summary_text: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
