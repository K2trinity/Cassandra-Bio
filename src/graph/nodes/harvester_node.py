"""Harvester workflow node implementation."""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        import logging

        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.harvest.agent import BioHarvestAgent
from src.graph.contracts import CONTRACT_VERSION, validate_bioharvest_output
from src.graph.state import AgentState


def harvester_node(state: AgentState) -> Dict[str, Any]:
    """Execute literature and trial harvesting for the workflow."""
    logger.info("🌾 NODE: HARVEST")

    try:
        agent = BioHarvestAgent()
        results = agent.run(user_query=state["user_query"], max_results_per_source=20)

        is_valid, errors = validate_bioharvest_output(results)
        if not is_valid:
            logger.warning("BioHarvest output contract validation failed")
            for err in errors[:8]:
                logger.warning(f"  - {err}")

        pdf_paths = []
        for item in results.get("results", []):
            local_path = item.get("local_path") if isinstance(item, dict) else None
            if local_path and os.path.exists(local_path):
                pdf_paths.append(local_path)

        logger.info(
            f"Harvest complete: {len(results.get('results', []))} records, {len(pdf_paths)} local PDFs"
        )

        return {
            "harvested_data": results.get("results", []),
            "harvest_data_layers": results.get("data_layers", {}),
            "harvest_source_payloads": results.get("source_payloads", {}),
            "harvest_frontend_payload": results.get("frontend_payload", {}),
            "dataflow_contract_version": CONTRACT_VERSION,
            "pdf_paths": pdf_paths,
            "project_name": state.get("project_name") or state.get("user_query", "").strip() or "Unknown",
            "status": "harvest_complete",
        }
    except Exception as exc:
        logger.error(f"Harvester failed: {exc}")
        return {
            "harvested_data": [],
            "pdf_paths": [],
            "errors": [f"Harvester: {str(exc)}"],
            "status": "harvest_failed",
        }


__all__ = ["harvester_node"]
