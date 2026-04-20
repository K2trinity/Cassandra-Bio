"""Harvest-owned LLM client factory.

This keeps Harvest-specific client instantiation out of src.
"""

import os

from src.llms.gemini_client import GeminiClient


def create_harvest_client() -> GeminiClient:
    """Create Gemini client for Harvest query planning/parsing."""
    return GeminiClient(
        model_name=os.getenv("HARVEST_MODEL_NAME", os.getenv("BIOHARVEST_MODEL_NAME", "gemini-2.5-flash")),
        temperature=float(os.getenv("HARVEST_TEMPERATURE", os.getenv("BIOHARVEST_TEMPERATURE", "0.3"))),
        max_output_tokens=int(os.getenv("HARVEST_MAX_TOKENS", os.getenv("BIOHARVEST_MAX_TOKENS", "4096"))),
    )
