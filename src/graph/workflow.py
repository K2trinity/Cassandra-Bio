"""LangGraph topology builder for Cassandra workflows."""

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import (
    extension_handoff_node,
    harvester_node,
    evidence_synthesizer_node,
    clinical_analyzer_node,
    quality_assessor_node,
    writer_node,
)
from src.graph.state import AgentState


def create_workflow() -> StateGraph:
    """Build the 6-node Cassandra analysis pipeline.

    Topology:
        START → harvester → extension_handoff → evidence_synthesizer
              → clinical_analyzer → quality_assessor → writer → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("harvester", harvester_node)
    workflow.add_node("extension_handoff", extension_handoff_node)
    workflow.add_node("evidence_synthesizer", evidence_synthesizer_node)
    workflow.add_node("clinical_analyzer", clinical_analyzer_node)
    workflow.add_node("quality_assessor", quality_assessor_node)
    workflow.add_node("writer", writer_node)

    workflow.add_edge(START, "harvester")
    workflow.add_edge("harvester", "extension_handoff")
    workflow.add_edge("extension_handoff", "evidence_synthesizer")
    workflow.add_edge("evidence_synthesizer", "clinical_analyzer")
    workflow.add_edge("clinical_analyzer", "quality_assessor")
    workflow.add_edge("quality_assessor", "writer")
    workflow.add_edge("writer", END)

    return workflow


__all__ = ["create_workflow"]
