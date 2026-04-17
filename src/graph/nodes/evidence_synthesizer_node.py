"""Evidence Synthesizer workflow node."""

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

from src.engines.evidence_synthesizer.agent import create_evidence_synthesizer
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def evidence_synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """Classify evidence layers and extract efficacy endpoints."""
    logger.info("🔬 NODE: EVIDENCE SYNTHESIZER")

    try:
        agent = create_evidence_synthesizer()
        harvested_data = state.get("harvested_data", []) or []
        data_layers = state.get("harvest_data_layers", {}) or {}

        synthesis = agent.synthesize(harvested_data, data_layers)

        extension_payloads = dict(state.get("extension_payloads", {}) or {})
        slot_payload = {
            "slot_id": "slot_a",
            "agent_name": "evidence_synthesizer",
            "data": {"evidence_synthesis": synthesis},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Evidence synthesizer output contract failed: {errors[:5]}")

        extension_payloads["slot_a"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "evidence_synthesis_complete",
        }
    except Exception as exc:
        logger.error(f"Evidence synthesizer failed: {exc}")
        return {
            "errors": [f"EvidenceSynthesizer: {str(exc)}"],
            "status": "evidence_synthesis_failed",
        }


__all__ = ["evidence_synthesizer_node"]
