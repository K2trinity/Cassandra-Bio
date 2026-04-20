"""Markdown assembly helpers for the objective biomedical analysis report engine."""

from __future__ import annotations

import re
from typing import Any, Optional, Protocol

from loguru import logger

from src.llms import create_report_client

from .models import DueDiligenceState
from .prompts import SYSTEM_PROMPT, build_user_prompt


class ReportLLM(Protocol):
    """Minimal interface expected from the report LLM client."""

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
        ...


def normalize_markdown(text: str) -> str:
    """Strip common wrapper artifacts and return clean Markdown."""

    if not text:
        return ""

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


def _fallback_markdown(state: DueDiligenceState) -> str:
    """Deterministic fallback when LLM output is unavailable."""

    disease_name = (
        state.disease_profile.disease_name
        if state.disease_profile is not None
        else "未提供"
    )
    burden_summary = (
        state.disease_profile.burden_summary
        if state.disease_profile is not None
        else "未提供"
    )
    unmet_need_summary = (
        state.disease_profile.unmet_need_summary
        if state.disease_profile is not None
        else "未提供"
    )
    catalog_size = len(state.drug_catalog)
    matrix_size = len(state.trial_data_matrix)

    return f"""# {state.report_title}

> Query: {state.user_query}
> Generated at: {state.generated_at.isoformat()}

## 一、疾病图谱与未满足需求 (Disease Landscape)

- Disease: {disease_name}
- Disease burden: {burden_summary}
- Unmet need: {unmet_need_summary}

## 二、药物类别与资产全景目录 (Drug Class & Asset Catalog)

- Catalog entries: {catalog_size}
- Asset (pipeline primary): {state.pipeline.asset_name}
- MoA: {state.pipeline.moa_description}
- Target: {state.pipeline.target_description}

## 三、公司/赞助方图谱与管线分布 (Company & Sponsor Landscape)

- Company: {state.company_profile.company_name}
- Cash runway: {state.company_profile.cash_runway_months if state.company_profile.cash_runway_months is not None else '未提供'} months
- R&D spend ratio: {state.company_profile.rd_spend_ratio if state.company_profile.rd_spend_ratio is not None else '未提供'}

## 四、临床进展与字段矩阵 (Clinical Progress Matrix)

- PubMed records: {len(state.clinical_evidence.pubmed_records)}
- Clinical trial records: {len(state.clinical_evidence.clinical_trial_records)}
- Safety signals: {len(state.clinical_evidence.safety_signals)}
- Trial matrix rows: {matrix_size}

- Target area: {state.competitive_landscape.target_area}
- Competitor count: {len(state.competitive_landscape.competitors)}
"""


def generate_due_diligence_report(
    state: DueDiligenceState,
    llm_client: Optional[ReportLLM] = None,
) -> str:
    """Generate the final Markdown report from validated state data.

    The function is intentionally fact-only: it should never emit price targets,
    stock recommendations, or buy/sell language.
    """

    active_llm = llm_client or create_report_client()
    user_prompt = build_user_prompt(state)

    try:
        response = active_llm.invoke(SYSTEM_PROMPT, user_prompt)
        if hasattr(response, "content"):
            response_text = str(response.content)
        else:
            response_text = str(response)
        markdown = normalize_markdown(response_text)
        if markdown:
            return markdown
        logger.warning("LLM returned empty Markdown, using fallback report text")
    except Exception as exc:
        logger.warning(f"LLM report generation failed, using fallback output: {exc}")

    return _fallback_markdown(state)