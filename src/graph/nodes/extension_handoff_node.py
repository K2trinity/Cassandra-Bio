"""Extension handoff workflow node.

This node is intentionally lightweight and keeps a stable interface boundary
between harvesting and report writing so future agents can be inserted here.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        import logging

        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.graph.state import AgentState


def extension_handoff_node(state: AgentState) -> Dict[str, Any]:
    """Prepare extension slots for future intermediate agents."""
    logger.info("🧩 NODE: EXTENSION HANDOFF")

    existing = state.get("extension_payloads")
    extension_payloads = existing if isinstance(existing, dict) else {}

    extension_payloads.setdefault("slot_a", {})
    extension_payloads.setdefault("slot_b", {})
    extension_payloads.setdefault("slot_c", {})
    extension_payloads.setdefault("slot_kline", {})

    # If anomaly signals arrived from the K-line widget, inject them
    # into the kline slot so downstream agents can reference them.
    anomaly_signals = state.get("kline_anomaly_signals") or []
    if anomaly_signals:
        extension_payloads["slot_kline"] = {
            "anomaly_signals": anomaly_signals,
            "status": "signals_received",
        }
        logger.info(f"🧩 Injected {len(anomaly_signals)} anomaly signals into slot_kline")

    return {
        "extension_payloads": extension_payloads,
        "status": "handoff_complete",
    }


__all__ = ["extension_handoff_node"]
