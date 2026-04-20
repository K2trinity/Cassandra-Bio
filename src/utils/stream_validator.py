"""Strict validation middleware for harvest LLM outputs.

This module sanitizes raw model responses and enforces a compact
harvest-oriented schema before data enters orchestration nodes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from loguru import logger


class StreamValidator:
    """Validate and normalize structured harvest payloads."""

    @staticmethod
    def sanitize_llm_json(raw_text: str) -> Dict[str, Any]:
        """Parse raw LLM output into a JSON object with robust fallback."""
        if not raw_text or not raw_text.strip():
            logger.warning("Empty LLM response received")
            return {"error": "Empty response", "raw": ""}

        text = raw_text.strip()
        text = re.sub(r"```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(text.lstrip())
            return obj
        except json.JSONDecodeError:
            logger.debug("JSONDecoder failed, falling back to regex extraction")

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                logger.error(f"JSON parse error: {exc}")

        return {"error": "No JSON found", "raw": raw_text[:300]}

    @staticmethod
    def validate_harvest_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce a stable harvest schema with safe defaults."""
        if "error" in data:
            logger.error(f"Harvest validation received error payload: {data.get('error')}")
            return {
                "scientific_summary": "Data extraction failed - invalid JSON output.",
                "risk_flags": ["JSON_PARSE_ERROR"],
                "stats": {"total": 0, "failed": 0},
                "key_failures": [],
                "error": data.get("error"),
            }

        validated = {
            "scientific_summary": (
                data.get("scientific_summary")
                or data.get("summary")
                or data.get("mechanism_summary")
                or "Summary extraction failed - check raw data."
            ),
            "risk_flags": data.get("risk_flags") or data.get("risks") or [],
            "stats": {
                "total": int(data.get("trials_analyzed", 0) or 0),
                "failed": int(data.get("failed_trials_count", 0) or 0),
            },
            "key_failures": data.get("key_failures") or [],
        }

        if not isinstance(validated["risk_flags"], list):
            validated["risk_flags"] = [str(validated["risk_flags"])]

        if not isinstance(validated["key_failures"], list):
            validated["key_failures"] = [str(validated["key_failures"])]

        logger.debug(
            "Harvest payload validated: "
            f"{validated['stats']['total']} trials, {len(validated['risk_flags'])} risk flags"
        )
        return validated

    @staticmethod
    def batch_validate(data_list: List[Dict[str, Any]], validator_type: str) -> List[Dict[str, Any]]:
        """Validate multiple payloads using harvest validators."""
        if validator_type not in {"harvest", "bioharvest"}:
            raise ValueError(f"Unknown validator type: {validator_type}")
        return [StreamValidator.validate_harvest_payload(data) for data in data_list]

    @staticmethod
    def validate_bioharvest_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible alias for harvest payload validation."""
        return StreamValidator.validate_harvest_payload(data)


# Convenience functions for direct use.
def clean_harvest_response(raw_llm_output: str) -> Dict[str, Any]:
    """One-step helper: sanitize then validate harvest response."""
    return StreamValidator.validate_harvest_payload(
        StreamValidator.sanitize_llm_json(raw_llm_output)
    )


def clean_bioharvest_response(raw_llm_output: str) -> Dict[str, Any]:
    """Backward-compatible alias for clean_harvest_response."""
    return clean_harvest_response(raw_llm_output)
