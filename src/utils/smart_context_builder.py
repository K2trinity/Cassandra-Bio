"""Token-aware context building utilities.

This module is the canonical utility location. The implementation currently
reuses the existing agent-level module during migration.
"""

from src.agents.smart_context_builder import ContextBudget, SmartContextBuilder, create_smart_context_builder

__all__ = ["ContextBudget", "SmartContextBuilder", "create_smart_context_builder"]
