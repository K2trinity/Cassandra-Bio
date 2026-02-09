"""
Cassandra Report Engine - Renderer Collection

Provides HTMLRenderer and PDFRenderer for biomedical due diligence report output.
Supports HTML and PDF formats with professional scientific styling.
"""

from .html_renderer import HTMLRenderer
from .pdf_renderer import PDFRenderer
from .pdf_layout_optimizer import (
    PDFLayoutOptimizer,
    PDFLayoutConfig,
    PageLayout,
    KPICardLayout,
    CalloutLayout,
    TableLayout,
    ChartLayout,
    GridLayout,
)
from .markdown_renderer import MarkdownRenderer

__all__ = [
    "HTMLRenderer",
    "PDFRenderer",
    "MarkdownRenderer",
    "PDFLayoutOptimizer",
    "PDFLayoutConfig",
    "PageLayout",
    "KPICardLayout",
    "CalloutLayout",
    "TableLayout",
    "ChartLayout",
    "GridLayout",
]
