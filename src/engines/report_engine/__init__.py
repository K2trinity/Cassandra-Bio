"""Canonical report engine entrypoint.

All report functionality should be imported from this package.
"""

from .core import ChapterStorage, DocumentComposer, TemplateSection, parse_template_sections
from .ir import (
	ALLOWED_BLOCK_TYPES,
	ALLOWED_INLINE_MARKS,
	CHAPTER_JSON_SCHEMA,
	CHAPTER_JSON_SCHEMA_TEXT,
	ENGINE_AGENT_TITLES,
	IRValidator,
	IR_VERSION,
)
from .nodes import ChapterGenerationNode, WordBudgetNode, create_chapter_generation_node, create_word_budget_node
from .renderers import (
	ChartLayout,
	CalloutLayout,
	GridLayout,
	HTMLRenderer,
	KPICardLayout,
	MarkdownRenderer,
	PageLayout,
	PDFLayoutConfig,
	PDFLayoutOptimizer,
	PDFRenderer,
	TableLayout,
)
from .utils import (
	ChartRepairer,
	ChartReviewService,
	ChartValidator,
	RepairResult,
	ReviewStats,
	ValidationResult,
	check_pango_available,
	create_chart_repairer,
	create_chart_validator,
	create_llm_repair_functions,
	get_chart_review_service,
	prepare_pango_environment,
)

__all__ = [
	"TemplateSection",
	"parse_template_sections",
	"ChapterStorage",
	"DocumentComposer",
	"ALLOWED_BLOCK_TYPES",
	"ALLOWED_INLINE_MARKS",
	"CHAPTER_JSON_SCHEMA",
	"CHAPTER_JSON_SCHEMA_TEXT",
	"ENGINE_AGENT_TITLES",
	"IRValidator",
	"IR_VERSION",
	"ChapterGenerationNode",
	"WordBudgetNode",
	"create_chapter_generation_node",
	"create_word_budget_node",
	"ChartLayout",
	"CalloutLayout",
	"GridLayout",
	"HTMLRenderer",
	"KPICardLayout",
	"MarkdownRenderer",
	"PageLayout",
	"PDFLayoutConfig",
	"PDFLayoutOptimizer",
	"PDFRenderer",
	"TableLayout",
	"ChartRepairer",
	"ChartReviewService",
	"ChartValidator",
	"RepairResult",
	"ReviewStats",
	"ValidationResult",
	"check_pango_available",
	"create_chart_repairer",
	"create_chart_validator",
	"create_llm_repair_functions",
	"get_chart_review_service",
	"prepare_pango_environment",
]
