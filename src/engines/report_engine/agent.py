"""Canonical report-writer agent entrypoint for engine callers.

This adapter keeps report invocation under src.engines.report_engine while
reusing the current report writer implementation.
"""

from __future__ import annotations

from src.agents.report_writer import ReportWriterAgent, create_agent


def create_report_agent() -> ReportWriterAgent:
    """Create a report writer agent via the engine-level interface."""
    return create_agent()


__all__ = ["ReportWriterAgent", "create_report_agent"]
