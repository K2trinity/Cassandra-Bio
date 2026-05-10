from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Literal

from loguru import logger

from src.llms import create_report_client

from .models import ClinicalTrialRecord, DiseaseChapterNarratives, DiseaseReportPackage


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
DISEASE_NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        **NARRATIVE_SCHEMA["properties"],
        "disease_evidence_synthesis_summary": {"type": "string"},
    },
    "required": [
        *NARRATIVE_SCHEMA["required"],
        "disease_evidence_synthesis_summary",
    ],
}
COMPANY_NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        **NARRATIVE_SCHEMA["properties"],
        "company_catalyst_and_rd_summary": {"type": "string"},
    },
    "required": [
        *NARRATIVE_SCHEMA["required"],
        "company_catalyst_and_rd_summary",
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
        is_company = package.disease_profile.target_type == "company"
        response_schema = COMPANY_NARRATIVE_SCHEMA if is_company else DISEASE_NARRATIVE_SCHEMA
        prompt = (
            "Write descriptive chapter summaries from this JSON data only.\n\n"
            f"{json.dumps(build_narrative_payload(package), ensure_ascii=False, indent=2, default=str)}"
        )

        try:
            response = self.client_factory().generate_json(
                prompt,
                response_schema=response_schema,
                system_instruction=_system_instruction(
                    selected_language,
                    company_mode=is_company,
                ),
                max_output_tokens=2400,
            )
        except Exception as exc:
            logger.warning(f"Disease report narrative generation failed: {exc}")
            return DiseaseChapterNarratives(language=selected_language)

        if not isinstance(response, dict):
            return DiseaseChapterNarratives(language=selected_language)

        required_keys = set(response_schema["required"])
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
        if is_company:
            values["company_catalyst_and_rd_summary"] = _clean_text(
                response.get("company_catalyst_and_rd_summary")
            )
        else:
            values["disease_evidence_synthesis_summary"] = _clean_text(
                response.get("disease_evidence_synthesis_summary")
            )
        if not any(values.values()):
            return DiseaseChapterNarratives(language=selected_language)

        return DiseaseChapterNarratives(language=selected_language, **values)


def build_narrative_payload(package: DiseaseReportPackage) -> dict[str, Any]:
    trials = package.clinical_trials
    risk_records = package.risk_records
    target_metadata = _target_metadata(package)
    counts = _stratum_counts(package)
    expansion_condition_counts = _expansion_condition_counts(package)
    is_company = package.disease_profile.target_type == "company"

    executive_summary: dict[str, Any] = {
        "disease_name": package.disease_profile.disease_name,
        **target_metadata,
        "retained_count": package.source_audit.retained_count,
        "rejected_count": package.source_audit.rejected_count,
        "latest_study_first_posted": _latest_study_first_posted(package),
        "status_distribution": dict(Counter(trial.status for trial in trials)),
        "top_sponsors": _top_values([trial.sponsor for trial in trials], limit=5),
        "stratum_counts": counts,
    }
    landscape: dict[str, Any] = {
        "disease_name": package.disease_profile.disease_name,
        **target_metadata,
        "trial_count": len(trials),
        "stratum_counts": counts,
        "phase_distribution": _phase_distribution(trials),
        "status_distribution": dict(Counter(trial.status for trial in trials)),
        "results_distribution": dict(Counter(trial.study_results for trial in trials)),
        "records": [
            {
                "study_title": trial.study_title,
                "nct_number": trial.nct_number,
                "status": trial.status,
                "primary_stratum": trial.primary_stratum,
                "strata": list(trial.strata),
                "phases": list(trial.phases),
                "has_results": trial.has_results,
                "study_results": trial.study_results,
                "results_first_posted": trial.results_first_posted,
                "last_update_posted": trial.last_update_posted,
                "conditions": list(trial.conditions),
                "interventions": list(trial.interventions),
                "sponsor": trial.sponsor,
                "study_type": trial.study_type,
                "primary_outcome_measures": list(trial.primary_outcome_measures),
                "secondary_outcome_measures": list(trial.secondary_outcome_measures),
                "enrollment": trial.enrollment,
            }
            for trial in trials
        ],
    }
    if is_company:
        executive_summary["expansion_condition_counts"] = expansion_condition_counts
        landscape["expansion_condition_counts"] = expansion_condition_counts

    payload = {
        "report_architecture": {
            "chapters": [
                {
                    "id": "executive_summary",
                    "purpose": "Shows report scope, source counts, and how to read the evidence layers.",
                },
                {
                    "id": "clinical_trial_and_pipeline_landscape",
                    "purpose": "Shows deduplicated ClinicalTrials.gov records with layer, phase, status, and results fields.",
                },
                {
                    "id": "pipeline_timeline_and_competition_risk",
                    "purpose": "Shows deterministic timeline and competition signals derived from retained records.",
                },
                _fourth_chapter_payload(is_company),
            ],
            "source_of_truth": "ClinicalTrials.gov fields are rendered directly; LLM text summarizes only supplied JSON.",
        },
        "executive_summary": executive_summary,
        "clinical_trial_and_pipeline_landscape": landscape,
        "pipeline_timeline_and_competition_risk": {
            "disease_name": package.disease_profile.disease_name,
            **target_metadata,
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
    if is_company:
        payload["company_pipeline_summary"] = _company_pipeline_summary(
            package,
            stratum_counts=counts,
            expansion_condition_counts=expansion_condition_counts,
        )
    else:
        payload["disease_evidence_synthesis"] = _disease_evidence_synthesis_payload(
            package,
            stratum_counts=counts,
        )
    return payload


def _fourth_chapter_payload(is_company: bool) -> dict[str, str]:
    if is_company:
        return {
            "id": "company_catalyst_and_rd_summary",
            "purpose": "Summarizes Catalyst Tracker, Expansion Map, and Track Record sections without inferring success.",
        }
    return {
        "id": "disease_evidence_synthesis_summary",
        "purpose": "Summarizes the first three disease chapters into a source-grounded disease-level conclusion.",
    }


def _system_instruction(
    language: Literal["zh", "en"],
    *,
    company_mode: bool = False,
) -> str:
    output_language = "Chinese" if language == "zh" else "English"
    length_instruction = (
        "160-320 Chinese characters per chapter."
        if language == "zh"
        else "90-160 English words per chapter."
    )
    instruction = (
        "You write objective biomedical report summaries from structured JSON only.\n"
        "Explain what each report section shows and what core point its data supports.\n"
        "Be direct and visual: name the report architecture, the ClinicalTrials layers, and the phase/status/results patterns.\n"
        "Use cautious wording such as 'the supplied dataset shows' and 'records indicate'.\n"
        "Do not infer missing facts.\n"
        "Do not create trials, sponsors, dates, results, endpoints, safety findings, efficacy claims, risk labels, or numeric values.\n"
        "Do not overwrite or correct source fields from ClinicalTrials.gov.\n"
        "Do not classify risk beyond deterministic labels already present in the JSON.\n"
        "If evidence is sparse, say data are insufficient instead of filling the gap.\n"
        "Return strict JSON only.\n"
        f"Write in {output_language}.\n"
        f"{length_instruction}"
    )
    if company_mode:
        instruction += (
            "\nFor company_catalyst_and_rd_summary, write a concise company-oriented clinical pipeline summary."
            "\nUse bold labels exactly as: **Catalyst Tracker:**, **Expansion Map:**, **Track Record:**."
            "\nKeep the company summary to 3 short sentences or compact clauses."
            "\nCatalyst Tracker means event-driven near-term readout focus."
            "\nExpansion Map means current recruiting R&D allocation."
            "\nTrack Record means result-bearing historical evidence; do not claim success rate unless supplied."
        )
    else:
        instruction += (
            "\nFor disease_evidence_synthesis_summary, summarize the first three chapters together."
            "\nUse only executive_summary, clinical_trial_and_pipeline_landscape, and pipeline_timeline_and_competition_risk JSON."
            "\nDo not reuse company labels such as Catalyst Tracker, Expansion Map, or Track Record."
            "\nFrame it as a disease-level evidence synthesis, not a company pipeline view."
        )
    return instruction


def _company_pipeline_summary(
    package: DiseaseReportPackage,
    *,
    stratum_counts: dict[str, int],
    expansion_condition_counts: dict[str, int],
) -> dict[str, Any]:
    trials = package.clinical_trials
    return {
        "target_type": "company",
        "company_name": package.disease_profile.company_name,
        "target_name": package.disease_profile.target_name,
        "section_order": ["Catalyst Tracker", "Expansion Map", "Track Record"],
        "stratum_counts": stratum_counts,
        "catalyst_tracker": {
            "purpose": "event-driven near-term readout focus",
            "count": stratum_counts.get("catalyst", 0),
            "records": _records_for_stratum(trials, "catalyst"),
        },
        "expansion_map": {
            "purpose": "current recruiting R&D allocation",
            "count": stratum_counts.get("expansion", 0),
            "condition_counts": expansion_condition_counts,
            "records": _records_for_stratum(trials, "expansion"),
        },
        "track_record": {
            "purpose": "result-bearing historical evidence, not inferred success rate",
            "count": stratum_counts.get("track_record", 0),
            "result_bearing_count": sum(
                1
                for trial in trials
                if _has_stratum(trial, "track_record") and trial.has_results
            ),
            "records": _records_for_stratum(trials, "track_record"),
        },
        "interpretation_rules": [
            "Use only supplied trial records and aggregate counts.",
            "Do not infer efficacy, safety, regulatory success, market success, or success rate.",
            "Keep the written company summary concise and label the three sections in bold.",
        ],
    }


def _disease_evidence_synthesis_payload(
    package: DiseaseReportPackage,
    *,
    stratum_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "target_type": "disease",
        "disease_name": package.disease_profile.disease_name,
        "section_order": [
            "Executive Summary",
            "Clinical Trial And Pipeline Landscape",
            "Pipeline Timeline And Competition Risk",
        ],
        "retained_count": package.source_audit.retained_count,
        "rejected_count": package.source_audit.rejected_count,
        "stratum_counts": stratum_counts,
        "phase_distribution": _phase_distribution(package.clinical_trials),
        "status_distribution": dict(Counter(trial.status for trial in package.clinical_trials)),
        "results_distribution": dict(Counter(trial.study_results for trial in package.clinical_trials)),
        "risk_distribution": {
            "timeline": dict(Counter(record.timeline_signal for record in package.risk_records)),
            "competition": dict(Counter(record.competition_signal for record in package.risk_records)),
        },
        "interpretation_rules": [
            "Synthesize only the first three disease chapters.",
            "Do not introduce company-mode Catalyst Tracker, Expansion Map, or Track Record framing.",
            "Do not infer efficacy, safety, approval odds, or market impact.",
        ],
    }


def _records_for_stratum(trials: list[Any], stratum: str, limit: int = 8) -> list[dict[str, Any]]:
    return [
        _trial_summary(trial)
        for trial in trials
        if _has_stratum(trial, stratum)
    ][:limit]


def _has_stratum(trial: Any, stratum: str) -> bool:
    return stratum in (trial.strata or [trial.primary_stratum])


def _trial_summary(trial: Any) -> dict[str, Any]:
    return {
        "study_title": trial.study_title,
        "nct_number": trial.nct_number,
        "status": trial.status,
        "conditions": list(trial.conditions),
        "phase": _join_list(trial.phases),
        "results": trial.study_results,
        "primary_completion_date": trial.primary_completion_date,
        "study_first_posted": trial.study_first_posted,
        "last_update_posted": trial.last_update_posted,
    }


def _latest_study_first_posted(package: DiseaseReportPackage) -> str | None:
    dates = [
        trial.study_first_posted
        for trial in package.clinical_trials
        if trial.study_first_posted is not None
    ]
    return max(dates).isoformat() if dates else None


def _target_metadata(package: DiseaseReportPackage) -> dict[str, str]:
    profile = package.disease_profile
    metadata = {
        "target_type": profile.target_type,
        "target_name": profile.target_name or profile.disease_name,
    }
    if profile.company_name:
        metadata["company_name"] = profile.company_name
    return metadata


def _stratum_counts(package: DiseaseReportPackage) -> dict[str, int]:
    details_counts = package.source_audit.details.get("stratum_counts")
    if isinstance(details_counts, dict):
        return {
            str(key): int(value)
            for key, value in details_counts.items()
            if isinstance(value, int)
        }

    counter: Counter[str] = Counter()
    for trial in package.clinical_trials:
        strata = trial.strata or [trial.primary_stratum or "unclassified"]
        counter.update(stratum for stratum in strata if stratum)
    return dict(counter)


def _expansion_condition_counts(package: DiseaseReportPackage) -> dict[str, int]:
    details_counts = package.source_audit.details.get("expansion_condition_counts")
    if isinstance(details_counts, dict):
        return {
            str(key): int(value)
            for key, value in details_counts.items()
            if isinstance(value, int)
        }
    return {}


def _top_values(values: list[str], limit: int) -> list[str]:
    counter = Counter(value for value in values if value and value != "Unknown")
    return [value for value, _count in counter.most_common(limit)]


def _phase_distribution(trials: list[ClinicalTrialRecord]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for trial in trials:
        phases = trial.phases or ["Unknown"]
        for phase in phases:
            counter[str(phase or "Unknown")] += 1
    return dict(counter)


def _join_list(values: list[str]) -> str:
    return ", ".join(value for value in values if value) or "-"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


__all__ = [
    "COMPANY_NARRATIVE_SCHEMA",
    "DISEASE_NARRATIVE_SCHEMA",
    "DiseaseReportNarrativeService",
    "NARRATIVE_SCHEMA",
    "build_narrative_payload",
]
