"""Compatibility exports for legacy ReportEngine.ir imports."""

from src.engines.report_engine.ir import (
    ALLOWED_BLOCK_TYPES,
    ALLOWED_INLINE_MARKS,
    CHAPTER_JSON_SCHEMA,
    CHAPTER_JSON_SCHEMA_TEXT,
    ENGINE_AGENT_TITLES,
    IR_VERSION,
    IRValidator,
)

__all__ = [
    "IR_VERSION",
    "CHAPTER_JSON_SCHEMA",
    "CHAPTER_JSON_SCHEMA_TEXT",
    "ALLOWED_BLOCK_TYPES",
    "ALLOWED_INLINE_MARKS",
    "ENGINE_AGENT_TITLES",
    "IRValidator",
]
