"""Harvest-owned LLM client factory.

This keeps Harvest-specific client instantiation out of src.
"""

from src.llms.gemini_client import GeminiClient, _settings_value


def create_harvest_client() -> GeminiClient:
    """Create Gemini client for Harvest query planning/parsing."""
    return GeminiClient(
        model_name=str(
            _settings_value(
                "HARVEST_MODEL_NAME",
                _settings_value("BIOHARVEST_MODEL_NAME", "gemini-3.1-flash-lite"),
            )
        ),
        temperature=float(
            _settings_value(
                "HARVEST_TEMPERATURE",
                _settings_value("BIOHARVEST_TEMPERATURE", "0.3"),
            )
        ),
        max_output_tokens=int(
            _settings_value(
                "HARVEST_MAX_TOKENS",
                _settings_value("BIOHARVEST_MAX_TOKENS", "4096"),
            )
        ),
    )
