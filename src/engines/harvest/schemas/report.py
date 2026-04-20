"""Typed output schema for BioHarvest facade."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .data_candidate import DataCandidate


class HarvestStats(BaseModel):
    """High-level counters returned by BioHarvest."""

    total: int = 0
    pubmed: int = 0
    trials: int = 0
    pdfs_downloaded: int = 0
    ncbi_records: int = 0
    openfda_records: int = 0


class HarvestReport(BaseModel):
    """Final response contract exposed by BioHarvest agent facade."""

    results: List[DataCandidate] = Field(default_factory=list)
    stats: HarvestStats = Field(default_factory=HarvestStats)
    data_layers: Dict[str, Any] = Field(default_factory=dict)
    source_payloads: Dict[str, Any] = Field(default_factory=dict)
    frontend_payload: Dict[str, Any] = Field(default_factory=dict)
