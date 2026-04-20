"""
Graph Package

This package contains the LangGraph orchestration components.
"""

from src.graph.state import AgentState


def create_workflow():
	"""Lazily import graph topology builder to avoid eager langgraph dependency."""
	from src.graph.workflow import create_workflow as _create_workflow

	return _create_workflow()

__all__ = ["AgentState", "create_workflow"]
