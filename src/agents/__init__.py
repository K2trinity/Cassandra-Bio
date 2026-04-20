"""
Cassandra Agents Module

This module contains specialized agents for biomedical research workflows.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "ReportWriterAgent",
    "ReportWriterAgentV2",
    "create_agent",
]


def __getattr__(name: str) -> Any:
    """Lazy-load heavy agent modules to avoid package import side effects."""
    if name in {"ReportWriterAgent", "create_agent"}:
        module = import_module("src.engines.report_engine.agent")
        if name == "create_agent":
            return getattr(module, "create_report_agent")
        return getattr(module, name)

    if name == "ReportWriterAgentV2":
        module = import_module("src.agents.report_writer_agent")
        return getattr(module, "ReportWriterAgent")

    raise AttributeError(f"module 'src.agents' has no attribute '{name}'")
