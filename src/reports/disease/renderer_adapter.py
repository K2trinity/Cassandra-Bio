from __future__ import annotations

import copy
import inspect
import json
import re
from pathlib import Path
from typing import Any

from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.engines.report_engine.renderers.markdown_renderer import MarkdownRenderer
from src.engines.report_engine.renderers.pdf_renderer import PDFRenderer
from src.reports.disease.models import DiseaseReportArtifacts


_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_REPEATED_UNDERSCORES = re.compile(r"_+")


def sanitize_report_filename(filename: str, max_length: int = 80) -> str:
    """Return a filesystem-safe report filename stem."""
    sanitized = _UNSAFE_FILENAME_CHARS.sub("_", str(filename or ""))
    sanitized = sanitized.replace(" ", "_")
    sanitized = _REPEATED_UNDERSCORES.sub("_", sanitized)
    sanitized = sanitized.strip("._- \t\r\n")
    if max_length > 0:
        sanitized = sanitized[:max_length].strip("._- \t\r\n")
    return sanitized or "disease_report"


class DiseaseReportRendererAdapter:
    """Render disease report IR to every report artifact from one input IR."""

    def __init__(
        self,
        markdown_renderer: Any | None = None,
        html_renderer: Any | None = None,
        pdf_renderer: Any | None = None,
    ) -> None:
        self.markdown_renderer = markdown_renderer or MarkdownRenderer()
        self.html_renderer = html_renderer or HTMLRenderer()
        self.pdf_renderer = pdf_renderer or PDFRenderer()

    def render_all(
        self,
        document_ir: Any,
        output_dir: str | Path,
        project_name: str,
    ) -> DiseaseReportArtifacts:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        base_name = sanitize_report_filename(project_name)
        ir_path = output_path / f"{base_name}.ir.json"
        markdown_path = output_path / f"{base_name}.md"
        html_path = output_path / f"{base_name}.html"
        pdf_path = output_path / f"{base_name}.pdf"

        source_ir = self._to_plain_ir(document_ir)
        ir_path.write_text(
            json.dumps(source_ir, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        ir_file_path = str(ir_path)

        markdown_content = _call_with_supported_kwargs(
            self.markdown_renderer.render,
            copy.deepcopy(source_ir),
            ir_file_path=ir_file_path,
        )
        markdown_path.write_text(markdown_content, encoding="utf-8")

        html_content = _call_with_supported_kwargs(
            self.html_renderer.render,
            copy.deepcopy(source_ir),
            ir_file_path=ir_file_path,
        )
        html_path.write_text(html_content, encoding="utf-8")

        rendered_pdf_path = _call_with_supported_kwargs(
            self.pdf_renderer.render_to_pdf,
            copy.deepcopy(source_ir),
            pdf_path,
            optimize_layout=True,
            ir_file_path=ir_file_path,
        )

        return DiseaseReportArtifacts(
            markdown_content=markdown_content,
            markdown_path=str(markdown_path),
            html_path=str(html_path),
            pdf_path=str(rendered_pdf_path or pdf_path),
            ir_path=str(ir_path),
        )

    def _to_plain_ir(self, document_ir: Any) -> dict[str, Any]:
        if hasattr(document_ir, "model_dump"):
            return document_ir.model_dump(mode="json")
        if hasattr(document_ir, "to_dict"):
            return document_ir.to_dict()
        if isinstance(document_ir, dict):
            return copy.deepcopy(document_ir)
        raise TypeError("document_ir must be a mapping or expose model_dump()/to_dict()")


def _call_with_supported_kwargs(method: Any, *args: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(method)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return method(*args, **kwargs)
    supported_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return method(*args, **supported_kwargs)


__all__ = ["DiseaseReportRendererAdapter", "sanitize_report_filename"]
