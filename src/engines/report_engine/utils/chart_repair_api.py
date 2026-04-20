"""Compatibility LLM repair API hooks.

This project currently uses local chart repairs by default, so this module
returns an empty hook list and keeps the old API stable.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from src.llms import create_report_client


LLMRepairFn = Callable[[Dict[str, Any], Any], Optional[Dict[str, Any]]]


def create_llm_repair_functions() -> List[LLMRepairFn]:
    """Return optional chart repair callables.

    Legacy callers expect this factory to exist even when no external repair
    backend is configured.
    """
    try:
        client = create_report_client()
    except Exception:
        return []

    def _repair_chart_payload(payload: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        try:
            response_text = client.invoke(
                "Repair malformed Chart.js widget payloads and return JSON only.",
                json.dumps(
                    {
                        "payload": payload,
                        "context": context,
                    },
                    ensure_ascii=False,
                ),
            )
            if not response_text:
                return None
            return json.loads(response_text)
        except Exception:
            return None

    return [_repair_chart_payload]


__all__ = ["LLMRepairFn", "create_llm_repair_functions"]
