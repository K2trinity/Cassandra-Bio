"""Typed biomedical data models."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DataCandidate(BaseModel):
    """Unified data record for literature and trial sources."""

    title: str
    source: str
    snippet: str
    link: str
    status: str
    date: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    local_path: Optional[str] = None

    # Trial-compatible top-level fields for template/direct access.
    nct_number: Optional[str] = None
    nct_id: Optional[str] = None
    study_url: Optional[str] = None
    url: Optional[str] = None
    acronym: Optional[str] = None
    study_status: Optional[str] = None
    brief_summary: Optional[str] = None
    has_results: Optional[str] = None
    study_results: Optional[str] = None
    results_url: Optional[str] = None
    phases: Optional[str] = None
    phase: Optional[str] = None
    study_design: Optional[str] = None
    why_stopped: Optional[str] = None
    interventions: Optional[str] = None
    conditions: Optional[str] = None
    primary_outcome_measures: Optional[str] = None
    secondary_outcome_measures: Optional[str] = None
    other_outcome_measures: Optional[str] = None
    sponsor: Optional[str] = None
    collaborators: Optional[str] = None
    funder_type: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[str] = None
    enrollment: Optional[str] = None
    study_type: Optional[str] = None
    other_ids: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    first_posted: Optional[str] = None
    results_first_posted: Optional[str] = None
    last_update_posted: Optional[str] = None
    study_documents: Optional[str] = None
