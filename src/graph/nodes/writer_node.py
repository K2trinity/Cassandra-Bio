"""Writer workflow node implementation."""

from __future__ import annotations

import importlib
import json
import re
from typing import Any, Dict, List


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        import logging

        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.report_engine.agent import create_report_agent
from src.engines.report_engine.disease_survey.aggregator import aggregate_survey_data
from src.engines.report_engine.disease_survey.composer import disease_survey_to_markdown
from src.graph.contracts import CONTRACT_VERSION, validate_writer_input
from src.graph.profile import build_biomedical_profile
from src.graph.state import AgentState

_DISEASE_SURVEY_KEYWORDS = ("alzheimer", "parkinson", "huntington", "multiple sclerosis", "als ", "amyotrophic")


def _is_disease_survey_query(query: str) -> bool:
    # TODO(human): Implement smarter disease survey detection.
    # Current approach: simple keyword match. Consider:
    #   - Checking for survey-intent words ("survey", "comprehensive", "landscape", "overview")
    #   - Reusing _detect_disease_name from the aggregator to avoid keyword duplication
    #   - Guarding against false positives (e.g. "alzheimer drug interaction checker")
    # Return True if this query should route to the disease survey renderer.
    return any(kw in (query or "").lower() for kw in _DISEASE_SURVEY_KEYWORDS)


def _build_harvest_context_text(user_query: str, harvested_data: List[Dict[str, Any]]) -> str:
    """Convert harvest records into a writer-compatible evidence context string."""
    chunks = [f"QUERY: {user_query}"]

    for idx, row in enumerate(harvested_data, 1):
        if not isinstance(row, dict):
            continue

        title = str(row.get("title") or "")
        summary = str(row.get("summary") or row.get("abstract") or "")
        source = str(row.get("source") or "")
        pmid = str(row.get("pmid") or "")
        nct_id = str(row.get("nct_id") or "")

        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metadata_excerpt = json.dumps(metadata, ensure_ascii=True)[:1200]

        block = (
            f"\n=== HARVEST RECORD {idx} ===\n"
            f"SOURCE: {source}\n"
            f"PMID: {pmid}\n"
            f"NCT_ID: {nct_id}\n"
            f"TITLE: {title}\n"
            f"SUMMARY: {summary}\n"
            f"METADATA: {metadata_excerpt}\n"
        )
        chunks.append(block)

        if len("\n".join(chunks)) > 120000:
            break

    return "\n".join(chunks)[:120000]


def writer_node(state: AgentState) -> Dict[str, Any]:
    """Render the final report from harvested data and extension handoff payloads."""
    logger.info("✍️ NODE: REPORT WRITER")

    try:
        agent = create_report_agent()

        harvested_data = state.get("harvested_data", []) or []
        user_query = state.get("user_query", "")
        compiled_context = _build_harvest_context_text(user_query, harvested_data)
        extension_payloads = state.get("extension_payloads", {}) or {}

        has_extensions = any(
            bool(extension_payloads.get(slot))
            for slot in ("slot_a", "slot_b", "slot_c")
        )
        analysis_status = "FULL_PIPELINE" if has_extensions else "HARVEST_ONLY"

        contract_payload = {
            "user_query": user_query,
            "harvest_data": {
                "query": user_query,
                "results": harvested_data,
                "data_layers": state.get("harvest_data_layers", {}),
                "source_payloads": state.get("harvest_source_payloads", {}),
                "frontend_payload": state.get("harvest_frontend_payload", {}),
            },
            "synthesis_sections": extension_payloads,
            "project_name": state.get("project_name"),
            "output_dir": "final_reports",
            "compiled_context_text": compiled_context,
            "analysis_status": analysis_status,
            "contract_version": CONTRACT_VERSION,
        }

        is_valid, errors = validate_writer_input(contract_payload)
        if not is_valid:
            logger.error("Writer input contract validation failed")
            for err in errors[:10]:
                logger.error(f"  - {err}")
            return {
                "final_report": "# Contract Validation Failed\n\nWriter input payload did not pass schema validation.",
                "errors": [f"Writer contract: {err}" for err in errors],
                "status": "writer_failed",
            }

        writer_payload = {
            "user_query": user_query,
            "harvest_data": contract_payload["harvest_data"],
            "synthesis_sections": extension_payloads,
            "project_name": state.get("project_name"),
            "output_dir": "final_reports",
            "compiled_context_text": compiled_context,
            "failed_count": 0,
            "total_files": len(state.get("pdf_paths", []) or []),
            "analysis_status": analysis_status,
            "failed_files": [],
            "contract_version": CONTRACT_VERSION,
        }

        is_disease_survey = _is_disease_survey_query(user_query)
        html_path = None
        pdf_path = None

        if is_disease_survey and harvested_data:
            survey_state = aggregate_survey_data(harvested_data, user_query)
            report_output = agent.write_report(**writer_payload)
            markdown = report_output.markdown_content if hasattr(report_output, "markdown_content") else str(report_output)
            report_path = getattr(report_output, "markdown_path", None)
            html_path = getattr(report_output, "html_path", None)
            pdf_path = getattr(report_output, "pdf_path", None)
        else:
            report_output = agent.write_report(**writer_payload)
            markdown = report_output.markdown_content if hasattr(report_output, "markdown_content") else str(report_output)
            report_path = getattr(report_output, "markdown_path", None)
            html_path = getattr(report_output, "html_path", None)
            pdf_path = getattr(report_output, "pdf_path", None)

        state_with_project = dict(state)
        if not state_with_project.get("project_name"):
            state_with_project["project_name"] = user_query.strip() or "Unknown"
        biomedical_profile = build_biomedical_profile(state_with_project)

        return {
            "final_report": markdown,
            "final_report_markdown": markdown,
            "final_report_path": report_path,
            "final_report_html_path": html_path,
            "final_report_pdf_path": pdf_path,
            "analysis_focus": analysis_status,
            "extension_payloads": extension_payloads,
            "biomedical_profile": biomedical_profile,
            "disease_areas": biomedical_profile.get("disease_areas", []),
            "drug_baselines": biomedical_profile.get("drug_baselines", []),
            "target_signals": biomedical_profile.get("target_signals", []),
            "company_entities": biomedical_profile.get("company_entities", []),
            "clinical_data": biomedical_profile.get("clinical_data", {}),
            "evidence_stats": biomedical_profile.get("evidence_stats", {}),
            "status": "writer_complete",
        }
    except Exception as exc:
        logger.error(f"Writer failed: {exc}")
        return {
            "final_report": f"# Report Generation Failed\n\nError: {str(exc)}",
            "errors": [f"Writer: {str(exc)}"],
            "status": "writer_failed",
        }


__all__ = ["writer_node"]
