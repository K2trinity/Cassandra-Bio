from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Literal

from loguru import logger

from src.llms import create_report_client

from .models import DiseaseChapterNarratives, DiseaseReportPackage


NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "clinical_trial_and_pipeline_landscape": {"type": "string"},
        "pipeline_timeline_and_competition_risk": {"type": "string"},
    },
    "required": [
        "executive_summary",
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
    ],
}


class DiseaseReportNarrativeService:
    def __init__(self, client_factory: Callable[[], Any] = create_report_client) -> None:
        self.client_factory = client_factory

    def generate(
        self,
        package: DiseaseReportPackage,
        language: Literal["zh", "en"] = "zh",
    ) -> DiseaseChapterNarratives:
        selected_language: Literal["zh", "en"] = "en" if language == "en" else "zh"
        prompt = (
            "Write descriptive chapter summaries from this JSON data only.\n\n"
            f"{json.dumps(build_narrative_payload(package), ensure_ascii=False, indent=2, default=str)}"
        )

        try:
            response = self.client_factory().generate_json(
                prompt,
                response_schema=NARRATIVE_SCHEMA,
                system_instruction=_system_instruction(selected_language),
                max_output_tokens=1200,
            )
        except Exception as exc:
            logger.warning(f"Disease report narrative generation failed: {exc}")
            return DiseaseChapterNarratives(language=selected_language)

        if not isinstance(response, dict):
            return DiseaseChapterNarratives(language=selected_language)

        required_keys = set(NARRATIVE_SCHEMA["required"])
        if not required_keys.issubset(response):
            return DiseaseChapterNarratives(language=selected_language)
        if not all(isinstance(response[key], str) for key in required_keys):
            return DiseaseChapterNarratives(language=selected_language)

        values = {
            "executive_summary": _clean_text(response.get("executive_summary")),
            "clinical_trial_and_pipeline_landscape": _clean_text(
                response.get("clinical_trial_and_pipeline_landscape")
            ),
            "pipeline_timeline_and_competition_risk": _clean_text(
                response.get("pipeline_timeline_and_competition_risk")
            ),
        }
        if not any(values.values()):
            return DiseaseChapterNarratives(language=selected_language)

        return DiseaseChapterNarratives(language=selected_language, **values)


def build_narrative_payload(package: DiseaseReportPackage) -> dict[str, Any]:
    trials = package.clinical_trials
    risk_records = package.risk_records
    return {
        "executive_summary": {
            "disease_name": package.disease_profile.disease_name,
            "retained_count": package.source_audit.retained_count,
            "rejected_count": package.source_audit.rejected_count,
            "latest_study_first_posted": _latest_study_first_posted(package),
            "status_distribution": dict(Counter(trial.status for trial in trials)),
            "top_sponsors": _top_values([trial.sponsor for trial in trials], limit=5),
        },
        "clinical_trial_and_pipeline_landscape": {
            "disease_name": package.disease_profile.disease_name,
            "trial_count": len(trials),
            "records": [
                {
                    "study_title": trial.study_title,
                    "nct_number": trial.nct_number,
                    "status": trial.status,
                    "conditions": list(trial.conditions),
                    "interventions": list(trial.interventions),
                    "sponsor": trial.sponsor,
                    "study_type": trial.study_type,
                }
                for trial in trials
            ],
        },
        "pipeline_timeline_and_competition_risk": {
            "disease_name": package.disease_profile.disease_name,
            "risk_records": [
                {
                    "nct_number": record.nct_number,
                    "study_title": record.study_title,
                    "sponsor": record.sponsor,
                    "status": record.status,
                    "intervention_category": record.intervention_category,
                    "timeline_signal": record.timeline_signal,
                    "timeline_evidence": record.timeline_evidence,
                    "competition_signal": record.competition_signal,
                    "competition_evidence": record.competition_evidence,
                }
                for record in risk_records
            ],
            "risk_distribution": {
                "timeline": dict(Counter(record.timeline_signal for record in risk_records)),
                "competition": dict(Counter(record.competition_signal for record in risk_records)),
            },
        },
    }


def _system_instruction(language: Literal["zh", "en"]) -> str:
    output_language = "Chinese" if language == "zh" else "English"
    length_instruction = (
        "80-180 Chinese characters per chapter."
        if language == "zh"
        else "60-120 English words per chapter."
    )
    return (
        "You write short descriptive summaries for a biomedical report.\n"
        "Use only the supplied JSON data.\n"
        "Do not infer missing facts.\n"
        "Do not create trials, sponsors, dates, risk labels, endpoints, or numeric values.\n"
        "Do not classify risk.\n"
        "Do not modify field values.\n"
        "Return strict JSON only.\n"
        f"Write in {output_language}.\n"
        f"{length_instruction}"
    )


def _latest_study_first_posted(package: DiseaseReportPackage) -> str | None:
    dates = [
        trial.study_first_posted
        for trial in package.clinical_trials
        if trial.study_first_posted is not None
    ]
    return max(dates).isoformat() if dates else None


def _top_values(values: list[str], limit: int) -> list[str]:
    counter = Counter(value for value in values if value and value != "Unknown")
    return [value for value, _count in counter.most_common(limit)]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


__all__ = [
    "DiseaseReportNarrativeService",
    "NARRATIVE_SCHEMA",
    "build_narrative_payload",
]
