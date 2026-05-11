from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.reports.disease.renderer_adapter import (
    DiseaseReportRendererAdapter,
    sanitize_report_filename,
)


class _FakeMarkdownRenderer:
    def __init__(self) -> None:
        self.received_snapshots = []
        self.received_refs = []
        self.ir_file_paths = []

    def render(self, document_ir, ir_file_path=None):
        self.received_snapshots.append(deepcopy(document_ir))
        self.received_refs.append(document_ir)
        self.ir_file_paths.append(ir_file_path)
        document_ir["renderer_mutation"] = "markdown"
        return "# Disease Report\n"


class _FakeHTMLRenderer:
    def __init__(self) -> None:
        self.received_snapshots = []
        self.received_refs = []
        self.ir_file_paths = []

    def render(self, document_ir, ir_file_path=None):
        self.received_snapshots.append(deepcopy(document_ir))
        self.received_refs.append(document_ir)
        self.ir_file_paths.append(ir_file_path)
        document_ir["renderer_mutation"] = "html"
        return "<html><body>Disease Report</body></html>"


class _FakePDFRenderer:
    def __init__(self) -> None:
        self.received_snapshots = []
        self.received_refs = []
        self.output_paths = []
        self.optimize_layout_values = []
        self.ir_file_paths = []

    def render_to_pdf(self, document_ir, output_path, optimize_layout=True, ir_file_path=None):
        self.received_snapshots.append(deepcopy(document_ir))
        self.received_refs.append(document_ir)
        self.output_paths.append(output_path)
        self.optimize_layout_values.append(optimize_layout)
        self.ir_file_paths.append(ir_file_path)
        document_ir["renderer_mutation"] = "pdf"
        output_path.write_bytes(b"%PDF-1.4\n")
        return output_path


class _MinimalMarkdownRenderer:
    def render(self, document_ir):
        return "# Minimal\n"


class _MinimalHTMLRenderer:
    def render(self, document_ir):
        return "<html>Minimal</html>"


class _MinimalPDFRenderer:
    def render_to_pdf(self, document_ir, output_path):
        output_path.write_bytes(b"%PDF-minimal\n")
        return output_path


def _table_block(**overrides):
    block = {
        "type": "table",
        "caption": "Trial table",
        "rows": [
            {
                "cells": [
                    {
                        "header": True,
                        "blocks": [{"type": "paragraph", "inlines": [{"text": "Study"}]}],
                    },
                    {
                        "header": True,
                        "blocks": [{"type": "paragraph", "inlines": [{"text": "Sponsor"}]}],
                    },
                ],
            },
            {
                "cells": [
                    {
                        "blocks": [{"type": "paragraph", "inlines": [{"text": "Trial A"}]}],
                    },
                    {
                        "blocks": [{"type": "paragraph", "inlines": [{"text": "Sponsor A"}]}],
                    },
                ],
            },
        ],
    }
    block.update(overrides)
    return block


def test_sanitize_report_filename_is_filesystem_safe():
    raw = '  Alzheimer / disease: pipeline* report? "draft" <v1> | \x00 name  '

    sanitized = sanitize_report_filename(raw, max_length=40)

    assert sanitized == "Alzheimer_disease_pipeline_report_draft"
    assert sanitize_report_filename("conduct a survey on Alzheimer disease") == "conduct_a_survey_on_Alzheimer_disease"
    assert sanitize_report_filename("a/b:c*d?e") == "a_b_c_d_e"
    assert len(sanitized) <= 40
    assert not any(char in sanitized for char in '\\/:*?"<>| ')
    assert sanitize_report_filename('////\x00    ""') == "disease_report"


def test_renderer_adapter_writes_all_artifacts_from_same_ir():
    markdown_renderer = _FakeMarkdownRenderer()
    html_renderer = _FakeHTMLRenderer()
    pdf_renderer = _FakePDFRenderer()
    adapter = DiseaseReportRendererAdapter(
        markdown_renderer=markdown_renderer,
        html_renderer=html_renderer,
        pdf_renderer=pdf_renderer,
    )
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as output_dir:
        document_ir = {
            "metadata": {"title": "Alzheimer / Pipeline?"},
            "chapters": [{"chapterId": "summary", "blocks": []}],
        }

        artifacts = adapter.render_all(
            document_ir=document_ir,
            output_dir=output_dir,
            project_name="Alzheimer / Pipeline?",
        )

        assert artifacts.markdown_content == "# Disease Report\n"
        for artifact_path in [
            artifacts.ir_path,
            artifacts.markdown_path,
            artifacts.html_path,
            artifacts.pdf_path,
        ]:
            assert artifact_path is not None
            assert Path(artifact_path).exists()

        assert json.loads(Path(artifacts.ir_path).read_text(encoding="utf-8")) == document_ir
        assert Path(artifacts.markdown_path).read_text(encoding="utf-8") == "# Disease Report\n"
        assert Path(artifacts.html_path).read_text(encoding="utf-8") == "<html><body>Disease Report</body></html>"
        assert Path(artifacts.pdf_path).read_bytes() == b"%PDF-1.4\n"

        assert markdown_renderer.received_snapshots[0] == document_ir
        assert html_renderer.received_snapshots[0] == document_ir
        assert pdf_renderer.received_snapshots[0] == document_ir
        assert markdown_renderer.received_refs[0] is not html_renderer.received_refs[0]
        assert markdown_renderer.received_refs[0] is not pdf_renderer.received_refs[0]
        assert html_renderer.received_refs[0] is not pdf_renderer.received_refs[0]
        assert "renderer_mutation" not in document_ir
        assert markdown_renderer.ir_file_paths == [artifacts.ir_path]
        assert html_renderer.ir_file_paths == [artifacts.ir_path]
        assert pdf_renderer.ir_file_paths == [artifacts.ir_path]
        assert pdf_renderer.optimize_layout_values == [True]


def test_renderer_adapter_supports_minimal_renderer_signatures():
    adapter = DiseaseReportRendererAdapter(
        markdown_renderer=_MinimalMarkdownRenderer(),
        html_renderer=_MinimalHTMLRenderer(),
        pdf_renderer=_MinimalPDFRenderer(),
    )
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as output_dir:
        artifacts = adapter.render_all(
            document_ir={"metadata": {}, "chapters": []},
            output_dir=output_dir,
            project_name="minimal renderer",
        )

        assert Path(artifacts.markdown_path).read_text(encoding="utf-8") == "# Minimal\n"
        assert Path(artifacts.html_path).read_text(encoding="utf-8") == "<html>Minimal</html>"
        assert Path(artifacts.pdf_path).read_bytes() == b"%PDF-minimal\n"


def test_html_renderer_respects_table_colgroup_and_wide_class():
    html = HTMLRenderer()._render_table(
        _table_block(
            metadata={"className": "clinical-trial-landscape"},
            colgroup=[
                {"key": "study", "width": "70%"},
                {"key": "sponsor", "width": "30%"},
            ],
        )
    )

    assert '<div class="table-wrap table-wrap--wide">' in html
    assert '<table class="clinical-trial-landscape">' in html
    assert '<col style="width: 70%">' in html
    assert '<col style="width: 30%">' in html


def test_html_renderer_uses_wide_wrapper_for_layout_hint_without_class_or_colgroup():
    html = HTMLRenderer()._render_table(_table_block(metadata={"layout": "wide-risk-table"}))

    assert 'class="table-wrap table-wrap--wide table-wrap--layout-wide-risk-table"' in html
    assert 'data-layout="wide-risk-table"' in html
    assert "<colgroup>" not in html
    assert '<table class="layout-wide-risk-table" data-layout="wide-risk-table">' in html


def test_html_renderer_rejects_unsafe_colgroup_width_css():
    html = HTMLRenderer()._render_table(
        _table_block(
            colgroup=[
                {"key": "study", "width": '10%; background-image: url("https://example.test/x")'},
                {"key": "sponsor", "width": "12rem"},
            ],
        )
    )

    assert '<col style="width: 12rem">' in html
    assert "background-image" not in html
    assert "https://example.test" not in html
    assert '<colgroup><col><col style="width: 12rem"></colgroup>' in html


def test_html_renderer_places_caption_before_colgroup():
    html = HTMLRenderer()._render_table(
        _table_block(
            caption="Disease trials",
            colgroup=[{"key": "study", "width": "70%"}, {"key": "sponsor", "width": "30%"}],
        )
    )

    assert html.index("<caption>Disease trials</caption>") < html.index("<colgroup>")


def test_html_renderer_includes_actual_wide_table_css():
    html = HTMLRenderer().render({"title": "Report", "metadata": {}, "chapters": []})

    assert ".table-wrap--wide table" in html
    assert "min-width: 960px" in html
    assert "max-width: none" in html


def test_html_renderer_plain_table_keeps_backward_compatible_markup():
    html = HTMLRenderer()._render_table(_table_block(caption=None))

    assert '<div class="table-wrap"><table>' in html
    assert "<colgroup>" not in html
    assert "table-wrap--wide" not in html
