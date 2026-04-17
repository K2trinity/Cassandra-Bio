# src/engines/report_engine/disease_survey/composer.py
"""Assembles all disease survey sections into a report dict.

Also provides DocumentComposer integration via build_disease_survey_document.
"""
from __future__ import annotations

from typing import Any, Dict

from .models import DiseaseSurveyState
from .renderer import (
    render_cns_benchmark,
    render_drug_pipeline,
    render_executive_summary,
    render_literature_review,
    render_market_landscape,
    render_safety_profile,
    render_sponsor_analysis,
    render_target_biology,
    render_trial_landscape,
)


def compose_disease_survey_report(state: DiseaseSurveyState) -> Dict[str, Any]:
    """Render all sections and return as a flat dict keyed by section name."""
    return {
        "executive_summary": render_executive_summary(state),
        "drug_pipeline": render_drug_pipeline(state),
        "trial_landscape": render_trial_landscape(state),
        "sponsor_analysis": render_sponsor_analysis(state),
        "target_biology": render_target_biology(state),
        "safety_profile": render_safety_profile(state),
        "literature_review": render_literature_review(state),
        "cns_benchmark": render_cns_benchmark(state),
        "market_landscape": render_market_landscape(state),
    }


def build_disease_survey_document(
    state: DiseaseSurveyState,
    report_id: str | None = None,
) -> Dict[str, Any]:
    """Wrap compose_disease_survey_report into a DocumentComposer IR document.

    Each section becomes a chapter with order, title, and a single data block.
    """
    from ..core import DocumentComposer

    if report_id is None:
        report_id = f"disease-survey-{state.disease_name.lower().replace(' ', '-')}"

    sections = compose_disease_survey_report(state)

    _SECTION_META = [
        ("executive_summary",  "Executive Summary",   10),
        ("drug_pipeline",      "Drug Pipeline",       20),
        ("trial_landscape",    "Trial Landscape",     30),
        ("sponsor_analysis",   "Sponsor Analysis",    40),
        ("target_biology",     "Target Biology",      50),
        ("safety_profile",     "Safety Profile",      60),
        ("literature_review",  "Literature Review",   70),
        ("cns_benchmark",      "CNS Benchmark",       80),
        ("market_landscape",   "Market Landscape",    90),
    ]

    chapters = []
    for key, title, order in _SECTION_META:
        chapters.append({
            "chapterId": key,
            "title": title,
            "order": order,
            "anchor": key,
            "blocks": [
                {
                    "type": "data",
                    "content": sections[key],
                }
            ],
        })

    metadata: Dict[str, Any] = {
        "title": f"{state.disease_name} Disease Survey",
        "disease_name": state.disease_name,
        "query": state.query,
        "generatedAt": state.generated_at.isoformat(),
    }

    composer = DocumentComposer()
    return composer.build_document(report_id, metadata, chapters)


__all__ = ["compose_disease_survey_report", "build_disease_survey_document"]
