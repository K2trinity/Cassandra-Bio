"""Clinical Analyzer workflow node."""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.clinical_analyzer.agent import create_clinical_analyzer
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def clinical_analyzer_node(state: AgentState) -> Dict[str, Any]:
    """Build pipeline matrix and extract safety signals from clinical data."""
    logger.info("🧪 NODE: CLINICAL ANALYZER")

    try:
        agent = create_clinical_analyzer()
        harvested_data = state.get("harvested_data", []) or []
        source_payloads = state.get("harvest_source_payloads", {}) or {}

        analysis = agent.analyze(harvested_data, source_payloads)

        extension_payloads = dict(state.get("extension_payloads", {}) or {})
        slot_payload = {
            "slot_id": "slot_b",
            "agent_name": "clinical_analyzer",
            "data": {"clinical_analysis": analysis},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Clinical analyzer output contract failed: {errors[:5]}")

        extension_payloads["slot_b"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "clinical_analysis_complete",
        }
    except Exception as exc:
        logger.error(f"Clinical analyzer failed: {exc}")
        return {
            "errors": [f"ClinicalAnalyzer: {str(exc)}"],
            "status": "clinical_analysis_failed",
        }


__all__ = ["clinical_analyzer_node"]
