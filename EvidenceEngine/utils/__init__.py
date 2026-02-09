"""
Cassandra Evidence Miner - Utility Functions Module
Provides text processing, JSON parsing, and other auxiliary functionality
"""

from .text_processing import (
    clean_json_tags,
    clean_markdown_tags, 
    remove_reasoning_from_output,
    extract_clean_response,
    update_state_with_search_results,
    format_search_results_for_prompt
)

__all__ = [
    "clean_json_tags",
    "clean_markdown_tags",
    "remove_reasoning_from_output", 
    "extract_clean_response",
    "update_state_with_search_results",
    "format_search_results_for_prompt",
]
