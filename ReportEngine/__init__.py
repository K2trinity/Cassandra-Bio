"""Compatibility package for legacy ReportEngine imports.

This package keeps old import paths working while the implementation lives
under src.engines.report_engine.
"""

from src.engines.report_engine import *  # noqa: F401,F403
