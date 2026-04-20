"""Custom exceptions for the BioHarvest package."""


class BioHarvestError(Exception):
    """Base error for all BioHarvest failures."""


class QueryParsingError(BioHarvestError):
    """Raised when query parsing from LLM output fails."""


class RetrievalError(BioHarvestError):
    """Raised when a data source retrieval fails critically."""


class AggregationError(BioHarvestError):
    """Raised when evidence aggregation fails."""


class DownloadError(BioHarvestError):
    """Raised when full-text attachment flow fails."""
