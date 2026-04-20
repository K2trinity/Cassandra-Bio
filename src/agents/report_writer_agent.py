"""Report writer agent entrypoint aligned with target architecture naming."""

from src.engines.report_engine.agent import ReportWriterAgent, create_report_agent


def create_agent() -> ReportWriterAgent:
	"""Backward-compatible alias to engine-level report writer factory."""
	return create_report_agent()

__all__ = ["ReportWriterAgent", "create_agent"]
