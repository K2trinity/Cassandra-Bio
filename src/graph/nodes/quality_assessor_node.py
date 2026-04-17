"""Quality Assessor workflow node."""

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

from src.engines.quality_assessor.agent import create_quality_assessor
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def quality_assessor_node(state: AgentState) -> Dict[str, Any]:
    """Assess data quality and assign confidence grade."""
    logger.info("📊 NODE: QUALITY ASSESSOR")

    try:
        agent = create_quality_assessor()
        harvested_data = state.get("harvested_data", []) or []
        extension_payloads = dict(state.get("extension_payloads", {}) or {})

        slot_a_data = extension_payloads.get("slot_a", {})
        slot_b_data = extension_payloads.get("slot_b", {})

        assessment = agent.assess(harvested_data, slot_a_data, slot_b_data)

        slot_payload = {
            "slot_id": "slot_c",
            "agent_name": "quality_assessor",
            "data": {"quality_assessment": assessment},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Quality assessor output contract failed: {errors[:5]}")

        extension_payloads["slot_c"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "quality_assessment_complete",
        }
    except Exception as exc:
        logger.error(f"Quality assessor failed: {exc}")
        return {
            "errors": [f"QualityAssessor: {str(exc)}"],
            "status": "quality_assessment_failed",
        }


__all__ = ["quality_assessor_node"]
