"""
Centralized LLM module for Cassandra.

All engines use the unified GeminiClient from this module.
"""

from .gemini_client import (
    GeminiClient,
    create_bioharvest_client,
    create_query_client,  # Backwards compatibility alias
    create_report_client,
)

__all__ = [
    "GeminiClient",
    "create_bioharvest_client",
    "create_query_client",  # Alias
    "create_report_client",
]
