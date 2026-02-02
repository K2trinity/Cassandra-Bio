"""
Centralized LLM module for Bio-Short-Seller.

All engines use the unified GeminiClient from this module.
"""

from .gemini_client import (
    GeminiClient,
    create_bioharvest_client,
    create_query_client,  # Backwards compatibility alias
    create_forensic_client,
    create_media_client,  # Backwards compatibility alias
    create_evidence_client,
    create_report_client,
)

__all__ = [
    "GeminiClient",
    "create_bioharvest_client",
    "create_query_client",  # Alias
    "create_forensic_client",
    "create_media_client",  # Alias
    "create_evidence_client",
    "create_report_client",
]
