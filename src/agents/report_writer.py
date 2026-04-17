"""Report Writer Agent - harvest-first report generator.

This module generates a structured markdown report from harvested records and
compiled context text. It intentionally keeps the interface simple and avoids
legacy multi-engine semantic fields.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.llms import create_report_client


PDF_INLINE_IMAGE_STRIP_THRESHOLD = 1_000_000


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        import logging

        return logging.getLogger(__name__)


logger = _resolve_logger()


def sanitize_filename(filename: str, max_length: int = 50) -> str:
    """Normalize file name for cross-platform saving."""
    illegal_chars = r'[\\/:*?"<>|\x00-\x1f]'
    cleaned = re.sub(illegal_chars, "_", filename or "")
    cleaned = cleaned.replace(" ", "_").strip("_. ")
    cleaned = re.sub(r"_+", "_", cleaned)

    if not cleaned:
        cleaned = "report"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("_. ")
    return cleaned


def _safe_text(value: Any, max_len: int = 5000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


@dataclass
class ReportData:
    """Normalized report input payload."""

    user_query: str
    project_name: str
    harvest_payload: Dict[str, Any]
    context_text: str
    metadata: Dict[str, Any]


@dataclass
class ReportOutput:
    """Generated report output."""

    markdown_content: str
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None
    pdf_path: Optional[str] = None
    analysis_position: str = "INCONCLUSIVE"
    data_confidence: float = 0.0
    signal_severity_score: float = 0.0

    @property
    def recommendation(self) -> str:
        """Backward-compatible alias for legacy callers."""
        return self.analysis_position

    @property
    def confidence_score(self) -> float:
        """Backward-compatible alias for legacy callers."""
        return self.data_confidence

    @property
    def risk_score(self) -> float:
        """Backward-compatible alias for legacy callers."""
        return self.signal_severity_score


class ReportWriterAgent:
    """Harvest-only report writer."""

    def __init__(self):
        self.llm = None
        try:
            self.llm = create_report_client()
            logger.info("Report Writer initialized with report client")
        except Exception as exc:
            logger.warning(f"Report client initialization failed, using deterministic mode: {exc}")

        prompt_path = Path(__file__).parent.parent / "prompts" / "report_writer" / "system.txt"
        if prompt_path.exists():
            self.synthesis_system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self.synthesis_system_prompt = (
                "You are a biomedical analyst. Produce objective, source-linked summaries "
                "from supplied harvested records and context text."
            )

    @staticmethod
    def _strip_excessive_inline_images(
        html_content: str,
        threshold: int = PDF_INLINE_IMAGE_STRIP_THRESHOLD,
    ) -> str:
        """Strip only very large data URI images before PDF rendering."""
        pattern = rf'src="data:image/[^"]{{{int(threshold)},}}"'
        return re.sub(pattern, 'src="" alt="[See HTML version for images]"', html_content)

    def run(self, report_type: str, rows: List[Dict[str, Any]], query: str = "") -> Dict[str, Any]:
        """Route a report request by type. Currently supports 'disease_survey'."""
        if report_type == "disease_survey":
            # Lazy imports to avoid circular dependency via report_engine/__init__.py
            from src.engines.report_engine.disease_survey.aggregator import aggregate_survey_data
            from src.engines.report_engine.disease_survey.composer import compose_disease_survey_report
            state = aggregate_survey_data(rows, query)
            return compose_disease_survey_report(state)
        raise ValueError(f"Unknown report_type: {report_type!r}")

    def write_report(
        self,
        user_query: str,
        harvest_data: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None,
        output_dir: str = "reports",
        compiled_context_text: str = "",
        failed_count: int = 0,
        total_files: int = 0,
        assessment_override: Optional[str] = None,
        risk_override: Optional[str] = None,
        analysis_status: str = "UNKNOWN",
        failed_files: Optional[List[str]] = None,
        contract_version: Optional[str] = None,
        **extra_payload: Any,
    ) -> ReportOutput:
        """Generate report from harvested payload and context text."""
        del extra_payload

        effective_assessment_override = assessment_override if assessment_override is not None else risk_override
        failed_files = failed_files or []

        payload = harvest_data if isinstance(harvest_data, dict) else {}
        rows = self._extract_harvest_rows(payload)
        resolved_project_name = _safe_text(project_name or user_query or "Unknown", 120)
        context_text = _safe_text(compiled_context_text, 240000) or self._compose_context_text(user_query, rows)

        signal_score = self._compute_signal_severity(context_text)
        data_confidence = self._compute_data_confidence(
            context_len=len(context_text),
            row_count=len(rows),
            failed_count=failed_count,
            total_files=total_files,
        )

        analysis_position = (
            _safe_text(effective_assessment_override, 80)
            if effective_assessment_override
            else self._derive_analysis_position(
                signal_score=signal_score,
                data_confidence=data_confidence,
                analysis_status=analysis_status,
                failed_count=failed_count,
                total_files=total_files,
            )
        )

        report_data = ReportData(
            user_query=_safe_text(user_query, 500),
            project_name=resolved_project_name,
            harvest_payload=payload,
            context_text=context_text,
            metadata={
                "analysis_status": analysis_status,
                "failed_count": int(failed_count or 0),
                "total_files": int(total_files or 0),
                "failed_files": [str(x) for x in failed_files],
                "contract_version": contract_version or "unknown",
            },
        )

        markdown_content = self._render_markdown(
            report_data=report_data,
            rows=rows,
            analysis_position=analysis_position,
            data_confidence=data_confidence,
            signal_score=signal_score,
        )

        markdown_path = self._save_markdown(
            markdown_content=markdown_content,
            output_dir=output_dir,
            project_name=resolved_project_name,
        )

        logger.info(
            "Report generated: "
            f"position={analysis_position}, confidence={data_confidence:.1f}, signal={signal_score:.1f}, "
            f"rows={len(rows)}"
        )

        return ReportOutput(
            markdown_content=markdown_content,
            markdown_path=markdown_path,
            analysis_position=analysis_position,
            data_confidence=data_confidence,
            signal_severity_score=signal_score,
        )

    def write_report_segmented(
        self,
        user_query: str,
        harvest_data: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None,
        output_dir: str = "reports",
        compiled_context_text: str = "",
        failed_count: int = 0,
        total_files: int = 0,
        assessment_override: Optional[str] = None,
        risk_override: Optional[str] = None,
        analysis_status: str = "UNKNOWN",
        failed_files: Optional[List[str]] = None,
        contract_version: Optional[str] = None,
        **extra_payload: Any,
    ) -> ReportOutput:
        """Compatibility path routed to single-pass generator."""
        return self.write_report(
            user_query=user_query,
            harvest_data=harvest_data,
            project_name=project_name,
            output_dir=output_dir,
            compiled_context_text=compiled_context_text,
            failed_count=failed_count,
            total_files=total_files,
            assessment_override=assessment_override,
            risk_override=risk_override,
            analysis_status=analysis_status,
            failed_files=failed_files,
            contract_version=contract_version,
            **extra_payload,
        )

    def _extract_harvest_rows(self, harvest_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = harvest_data.get("results")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return []

    def _compose_context_text(self, user_query: str, rows: List[Dict[str, Any]]) -> str:
        parts = [f"QUERY: {_safe_text(user_query, 1000)}"]
        for idx, row in enumerate(rows, 1):
            title = _safe_text(row.get("title"), 500)
            summary = _safe_text(row.get("summary") or row.get("abstract"), 3000)
            source = _safe_text(row.get("source"), 100)
            pmid = _safe_text(row.get("pmid"), 80)
            nct_id = _safe_text(row.get("nct_id"), 80)
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            metadata_excerpt = json.dumps(metadata, ensure_ascii=True)[:1200]
            parts.append(
                "\n".join(
                    [
                        f"=== HARVEST RECORD {idx} ===",
                        f"SOURCE: {source}",
                        f"PMID: {pmid}",
                        f"NCT_ID: {nct_id}",
                        f"TITLE: {title}",
                        f"SUMMARY: {summary}",
                        f"METADATA: {metadata_excerpt}",
                    ]
                )
            )
            if len("\n\n".join(parts)) > 120000:
                break
        return "\n\n".join(parts)[:120000]

    def _compute_signal_severity(self, context_text: str) -> float:
        if not context_text:
            return 0.0

        text = context_text.lower()
        weighted_patterns = [
            (r"serious adverse|severe adverse|fatal|death", 2.2),
            (r"terminated|withdrawn|discontinued", 1.8),
            (r"toxicity|safety concern|black box", 1.7),
            (r"no significant|p\s*[>=]\s*0\.05", 1.2),
            (r"failed|failure|did not meet", 1.3),
            (r"insufficient|limited|uncertain", 0.8),
        ]

        score = 0.0
        for pattern, weight in weighted_patterns:
            count = len(re.findall(pattern, text))
            score += min(count, 12) * weight

        normalized = min(10.0, round(score / 6.0, 2))
        return normalized

    def _compute_data_confidence(
        self,
        context_len: int,
        row_count: int,
        failed_count: int,
        total_files: int,
    ) -> float:
        if total_files > 0:
            success_ratio = max(0.0, (total_files - max(0, failed_count)) / total_files)
        else:
            success_ratio = 1.0

        context_score = min(1.0, context_len / 6000.0)
        row_score = min(1.0, row_count / 20.0)
        confidence = (success_ratio * 0.5 + context_score * 0.3 + row_score * 0.2) * 10.0
        return round(max(0.0, min(10.0, confidence)), 2)

    def _derive_analysis_position(
        self,
        signal_score: float,
        data_confidence: float,
        analysis_status: str,
        failed_count: int,
        total_files: int,
    ) -> str:
        status_upper = (analysis_status or "").upper()
        if "CRITICAL_FAILURE" in status_upper:
            return "CRITICAL_FAILURE"
        if total_files > 0 and failed_count >= total_files:
            return "CRITICAL_FAILURE"
        if signal_score >= 7.0:
            return "SEVERE_NEGATIVE_SIGNAL"
        if signal_score >= 5.0:
            return "ELEVATED_NEGATIVE_SIGNAL"
        if signal_score >= 3.0:
            return "MIXED_SIGNAL"
        if data_confidence < 3.0:
            return "INCONCLUSIVE"
        return "LIMITED_NEGATIVE_SIGNAL"

    def _extract_signal_highlights(self, context_text: str, max_items: int = 8) -> List[str]:
        if not context_text:
            return []

        lines = [ln.strip() for ln in context_text.splitlines() if ln.strip()]
        picked: List[str] = []
        trigger = re.compile(
            r"adverse|toxicity|terminated|withdrawn|failed|insufficient|uncertain|no significant",
            re.IGNORECASE,
        )

        for line in lines:
            if trigger.search(line):
                picked.append(_safe_text(line, 220))
            if len(picked) >= max_items:
                break
        return picked

    def _render_markdown(
        self,
        report_data: ReportData,
        rows: List[Dict[str, Any]],
        analysis_position: str,
        data_confidence: float,
        signal_score: float,
    ) -> str:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = report_data.metadata.get("analysis_status", "UNKNOWN")
        failed_count = int(report_data.metadata.get("failed_count", 0) or 0)
        total_files = int(report_data.metadata.get("total_files", 0) or 0)
        failed_files = report_data.metadata.get("failed_files", []) or []
        contract_version = report_data.metadata.get("contract_version", "unknown")

        highlights = self._extract_signal_highlights(report_data.context_text)

        lines: List[str] = []
        lines.append(f"# {report_data.project_name} - Biomedical Review")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append(f"- Analysis Position: {analysis_position}")
        lines.append(f"- Data Confidence: {data_confidence:.2f}/10")
        lines.append(f"- Signal Severity Score: {signal_score:.2f}/10")
        lines.append(f"- Harvest Records: {len(rows)}")
        lines.append(f"- Processing Status: {status}")
        lines.append("")

        lines.append("## Run Metadata")
        lines.append(f"- Query: {report_data.user_query}")
        lines.append(f"- Generated At: {generated_at}")
        lines.append(f"- Contract Version: {contract_version}")
        if total_files > 0:
            lines.append(f"- File Processing: {max(total_files - failed_count, 0)}/{total_files} successful")
        if failed_files:
            lines.append("- Failed Files:")
            for item in failed_files[:20]:
                lines.append(f"  - {item}")
        lines.append("")

        lines.append("## Key Signal Highlights")
        if highlights:
            for item in highlights:
                lines.append(f"- {item}")
        else:
            lines.append("- No explicit high-signal statements were detected in compiled context text.")
        lines.append("")

        lines.append("## Harvest Record Snapshot")
        if rows:
            for idx, row in enumerate(rows[:25], 1):
                title = _safe_text(row.get("title"), 280) or "(untitled)"
                source = _safe_text(row.get("source"), 80) or "(unknown source)"
                year = _safe_text(row.get("year") or row.get("publication_year"), 10)
                pmid = _safe_text(row.get("pmid"), 40)
                nct_id = _safe_text(row.get("nct_id"), 40)
                summary = _safe_text(row.get("summary") or row.get("abstract"), 420)
                lines.append(f"### Record {idx}")
                lines.append(f"- Title: {title}")
                lines.append(f"- Source: {source}")
                if year:
                    lines.append(f"- Year: {year}")
                if pmid:
                    lines.append(f"- PMID: {pmid}")
                if nct_id:
                    lines.append(f"- NCT ID: {nct_id}")
                if summary:
                    lines.append(f"- Summary: {summary}")
                lines.append("")
        else:
            lines.append("- No harvest records were provided.")
            lines.append("")

        lines.append("## Context Excerpt")
        context_excerpt = _safe_text(report_data.context_text, 12000)
        if context_excerpt:
            lines.append("```text")
            lines.append(context_excerpt)
            lines.append("```")
        else:
            lines.append("No compiled context text available.")

        return "\n".join(lines).strip() + "\n"

    def _save_markdown(self, markdown_content: str, output_dir: str, project_name: str) -> Optional[str]:
        try:
            output_path = Path(output_dir or "final_reports")
            output_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_project = sanitize_filename(project_name, max_length=80)
            markdown_file = output_path / f"{safe_project}_{timestamp}.md"
            markdown_file.write_text(markdown_content, encoding="utf-8")
            return str(markdown_file)
        except Exception as exc:
            logger.warning(f"Failed to save markdown report: {exc}")
            return None


def create_agent() -> ReportWriterAgent:
    """Factory function for report writer agent."""
    return ReportWriterAgent()


__all__ = ["ReportWriterAgent", "ReportOutput", "ReportData", "create_agent"]
