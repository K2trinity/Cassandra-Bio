"""Harvest-local JSON sanitizer for LLM outputs."""

import json
import re
from typing import Any, Dict

from .._logging import logger


def sanitize_llm_json(raw_text: str) -> Dict[str, Any]:
    """Clean markdown artifacts and parse best-effort JSON object."""
    if not raw_text or not raw_text.strip():
        logger.warning("Empty LLM response received")
        return {"error": "Empty response", "raw": ""}

    text = raw_text.strip()
    text = re.sub(r"```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"```\s*", "", text)

    decoder = json.JSONDecoder()
    text_stripped = text.lstrip()
    try:
        obj, _ = decoder.raw_decode(text_stripped)
        return obj
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        clean_json = match.group(0)
        try:
            return json.loads(clean_json)
        except json.JSONDecodeError as exc:
            logger.error(f"JSON parse error: {exc}")

    logger.error("No valid JSON structure found in LLM response")
    return {"error": "No JSON found", "raw": raw_text[:200]}
