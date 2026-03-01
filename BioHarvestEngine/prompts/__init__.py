"""
Prompt模块
定义BioHarvest Agent使用的系统提示词
"""

from .prompts import (
    output_schema_bioharvest,
    output_schema_clinical_search,
    SYSTEM_PROMPT_BIOHARVEST,
    SYSTEM_PROMPT_SEARCH_PLANNING,
    SYSTEM_PROMPT_BIOHARVEST_SYNTHESIS
)

__all__ = [
    "SYSTEM_PROMPT_REPORT_STRUCTURE",
    "SYSTEM_PROMPT_FIRST_SEARCH", 
    "SYSTEM_PROMPT_FIRST_SUMMARY",
    "SYSTEM_PROMPT_REFLECTION",
    "SYSTEM_PROMPT_REFLECTION_SUMMARY",
    "SYSTEM_PROMPT_REPORT_FORMATTING",
    "output_schema_report_structure",
    "output_schema_first_search",
    "output_schema_first_summary", 
    "output_schema_reflection",
    "output_schema_reflection_summary",
    "input_schema_report_formatting"
]
