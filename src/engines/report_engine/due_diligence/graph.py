"""LangGraph nodes for the objective biomedical analysis report engine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from .models import DueDiligenceState
from .renderer import generate_due_diligence_report


class DueDiligenceGraphState(TypedDict, total=False):
    """Runtime state passed through LangGraph."""

    input_state: Dict[str, Any]
    validated_state: Dict[str, Any]
    validation_errors: List[str]
    report_markdown: str


def validate_due_diligence_state_node(state: DueDiligenceGraphState) -> Dict[str, Any]:
    """Validate raw graph input against the Pydantic state model."""

    raw_state = state.get("input_state") or {}
    try:
        validated = DueDiligenceState.model_validate(raw_state)
        return {
            "validated_state": validated.model_dump(mode="json"),
            "validation_errors": [],
        }
    except ValidationError as exc:
        return {
            "validation_errors": [str(exc)],
        }


def create_due_diligence_writer_node(llm_client: Optional[Any] = None):
    """Create the report writer node used by LangGraph."""

    def _writer(state: DueDiligenceGraphState) -> Dict[str, Any]:
        validated_payload = state.get("validated_state") or state.get("input_state") or {}
        validated_state = DueDiligenceState.model_validate(validated_payload)
        markdown = generate_due_diligence_report(validated_state, llm_client=llm_client)
        return {"report_markdown": markdown}

    return _writer


def build_due_diligence_graph(llm_client: Optional[Any] = None):
    """Build a minimal LangGraph pipeline for the report engine."""

    workflow = StateGraph(DueDiligenceGraphState)

    workflow.add_node("validate_state", validate_due_diligence_state_node)
    workflow.add_node("write_report", create_due_diligence_writer_node(llm_client))

    workflow.set_entry_point("validate_state")
    workflow.add_edge("validate_state", "write_report")
    workflow.add_edge("write_report", END)

    return workflow.compile()