"""Typed schemas used across BioHarvest layers."""

from .query import QueryIntent
from .data_candidate import DataCandidate
from .report import HarvestReport, HarvestStats


def model_dump_compat(model, **kwargs):
    """Support both Pydantic v1 and v2 dump APIs."""
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


__all__ = [
    "QueryIntent",
    "DataCandidate",
    "HarvestStats",
    "HarvestReport",
    "model_dump_compat",
]
