from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.engines.report_engine.renderers.pdf_layout_optimizer import PDFLayoutOptimizer


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "inlines": [{"text": text}]}


def test_wide_table_pdf_layout_uses_dense_wrapping_and_column_metadata():
    renderer = HTMLRenderer()
    block = {
        "type": "table",
        "caption": "Multidimensional clinical and commercial risk assessment",
        "metadata": {
            "layout": "wide-risk-assessment-table",
            "className": "clinical-commercial-risk-assessment",
        },
        "colgroup": [
            {"key": "candidate_sponsor", "width": "16%"},
            {"key": "clinical_evidence", "width": "42%"},
            {"key": "commercial_risk", "width": "42%"},
        ],
        "rows": [
            {
                "cells": [
                    {"header": True, "blocks": [_paragraph("Candidate / Sponsor")]},
                    {"header": True, "blocks": [_paragraph("Clinical Evidence Snapshot")]},
                    {"header": True, "blocks": [_paragraph("Operational And Commercial Risk Cue")]},
                ]
            },
            {
                "cells": [
                    {"blocks": [_paragraph("Asset X (Sponsor X)")]},
                    {
                        "blocks": [
                            _paragraph(
                                "Long evidence text with mechanism, phase, endpoint, and safety context "
                                "that must wrap inside a PDF table cell instead of expanding the column."
                            )
                        ]
                    },
                    {
                        "blocks": [
                            _paragraph(
                                "Long commercial risk text with diagnostics, monitoring requirements, "
                                "payer friction, launch readiness, and operational burden."
                            )
                        ]
                    },
                ]
            },
        ],
    }

    table_html = renderer._render_table(block)
    css = renderer._build_css({})

    assert 'table-wrap--wide' in table_html
    assert 'table-wrap--layout-wide-risk-assessment-table' in table_html
    assert 'data-layout="wide-risk-assessment-table"' in table_html
    assert "<thead>" in table_html
    assert 'data-column="Clinical Evidence Snapshot"' in table_html
    assert 'data-column-key="clinical_evidence"' in table_html
    assert ".table-wrap--wide table" in css
    assert ".table-wrap--wide th," in css
    assert ".table-wrap--wide td p" in css
    assert "overflow-wrap: anywhere" in css


def test_pdf_layout_optimizer_preserves_wide_table_dense_rules_after_generic_table_css():
    css = PDFLayoutOptimizer().generate_pdf_css()

    generic_table_index = css.index("/* Table optimization - strict overflow prevention */")
    wide_table_index = css.index("/* Wide report table overrides */")

    assert wide_table_index > generic_table_index
    assert ".table-wrap--wide table" in css
    assert "min-width: 0 !important" in css
    assert ".table-wrap--wide th," in css
    assert ".table-wrap--wide td p" in css
    assert "overflow-wrap: anywhere !important" in css
