"""Typed model for parsed user query intent."""

from typing import List

from pydantic import BaseModel, Field


class QueryIntent(BaseModel):
    """Normalized search intent for downstream retrievers."""

    core_entity: str = ""
    pubmed: List[str] = Field(default_factory=list)
    clinicaltrials: List[str] = Field(default_factory=list)
    original_query: str = ""
