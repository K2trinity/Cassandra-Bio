"""Regression tests for markdown fallback rendering."""

import re

from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.engines.report_engine.renderers.pdf_renderer import PDFRenderer


def test_html_renderer_render_from_markdown_renders_headings_and_tables():
    renderer = HTMLRenderer()

    html = renderer.render_from_markdown(
        "# Title\n\n## Section\n\n| A | B |\n| --- | --- |\n| 1 | 2 |",
        title="Fallback",
        query="Fallback",
    )

    assert "<h1" in html
    assert "<table" in html


def _sample_document_ir():
    return {
        "version": "1.0",
        "reportId": "disease-survey-test",
        "metadata": {
            "title": "Disease Survey",
            "query": "Alzheimer disease landscape",
        },
        "themeTokens": {},
        "assets": {},
        "chapters": [
            {
                "chapterId": "executive_summary",
                "title": "Executive Summary",
                "order": 10,
                "anchor": "executive_summary",
                "blocks": [
                    {
                        "type": "heading",
                        "level": 2,
                        "text": "Executive Summary",
                        "anchor": "executive_summary",
                    },
                    {"type": "paragraph", "inlines": [{"text": "Overview text."}]},
                ],
            },
            {
                "chapterId": "market_landscape",
                "title": "Market Landscape",
                "order": 20,
                "anchor": "market_landscape",
                "blocks": [
                    {
                        "type": "heading",
                        "level": 2,
                        "text": "Market Landscape",
                        "anchor": "market_landscape",
                    },
                    {"type": "paragraph", "inlines": [{"text": "Market text."}]},
                ],
            },
        ],
    }


def test_html_renderer_preserves_multiword_heading_titles():
    renderer = HTMLRenderer()

    html = renderer.render(_sample_document_ir())

    assert "一、 Executive Summary" in html
    assert "二、 Market Landscape" in html
    assert "一、 Summary" not in html
    assert "二、 Landscape" not in html


def test_html_renderer_uses_left_aligned_paragraphs_for_readability():
    renderer = HTMLRenderer()

    html = renderer.render(_sample_document_ir())

    assert "text-align: left;" in html
    assert "text-align: justify;" not in html


def test_pdf_renderer_registers_bold_font_face_for_embedded_report_font():
    renderer = PDFRenderer()

    html = renderer._get_pdf_html(_sample_document_ir(), optimize_layout=False)

    assert re.search(
        r"@font-face\s*\{[^}]*font-family: 'SourceHanSerif';[^}]*font-weight: 700;",
        html,
        re.S,
    )
