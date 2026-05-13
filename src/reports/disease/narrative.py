from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Literal

from loguru import logger

from src.llms import create_report_client

from .models import ClinicalTrialRecord, DiseaseChapterNarratives, DiseaseReportPackage
from .report_modes import get_report_mode_config


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
        "industry_landscape_summary": {"type": "string"},
    },
    "required": [
        *NARRATIVE_SCHEMA["required"],
        "disease_evidence_synthesis_summary",
        "industry_landscape_summary",
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
                max_output_tokens=3600,
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
            values["industry_landscape_summary"] = _clean_text(
                response.get("industry_landscape_summary")
            )
        if not any(values.values()):
            return DiseaseChapterNarratives(language=selected_language)

        return DiseaseChapterNarratives(language=selected_language, **values)


def build_narrative_payload(package: DiseaseReportPackage) -> dict[str, Any]:
    trials = package.clinical_trials
    risk_records = package.risk_records
    mode_config = get_report_mode_config(package.source_audit.details.get("report_mode"))
    representative_trials = trials[: mode_config.narrative_record_cap]
    representative_risk_records = risk_records[: mode_config.narrative_risk_record_cap]
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
        "termination_context": _termination_context(trials),
    }
    landscape: dict[str, Any] = {
        "disease_name": package.disease_profile.disease_name,
        **target_metadata,
        "trial_count": len(trials),
        "representative_record_count": len(representative_trials),
        "stratum_counts": counts,
        "phase_distribution": _phase_distribution(trials),
        "status_distribution": dict(Counter(trial.status for trial in trials)),
        "results_distribution": dict(Counter(trial.study_results for trial in trials)),
        "termination_context": _termination_context(trials),
        "records": [
            {
                "study_title": trial.study_title,
                "nct_number": trial.nct_number,
                "status": trial.status,
                "why_stopped": trial.why_stopped,
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
            for trial in representative_trials
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
                for record in representative_risk_records
            ],
            "risk_record_count": len(risk_records),
            "representative_risk_record_count": len(representative_risk_records),
            "risk_distribution": {
                "timeline": dict(Counter(record.timeline_signal for record in risk_records)),
                "competition": dict(Counter(record.competition_signal for record in risk_records)),
            },
            "termination_context": _termination_context(trials),
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
        payload["industry_landscape_context"] = _industry_landscape_payload(
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
        "Executive summary: 160-320 Chinese characters. "
        "Chapter two and three may be longer: 320-620 Chinese characters each, but remain data-grounded. "
        "Disease synthesis: 240-420 Chinese characters. "
        "Industry Landscape Summary: 450-800 Chinese characters with future outlook."
        if language == "zh"
        else "Executive summary: 90-160 English words. "
        "Chapter two and three may be longer: 160-280 English words each, but remain data-grounded. "
        "Disease synthesis: 120-220 English words. "
        "Industry Landscape Summary: 220-360 English words with future outlook."
    )
    instruction = (
        "You write objective biomedical report summaries from structured JSON only.\n"
        "Each returned field is rendered as the opening brief for its report chapter.\n"
        "Explain what each report section shows and what core point its data supports.\n"
        "For TERMINATED, WITHDRAWN, or SUSPENDED records, use why_stopped when supplied; if absent, explicitly say the source does not report a stop reason.\n"
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
            "\nFor Industry Landscape Summary, combine the supplied disease report context with cautious general biomedical industry context and a future outlook."
            "\nClearly separate dataset-supported observations from broader industry interpretation."
            "\nDo not invent trial-specific scientific, safety, regulatory, or commercial reasons for stopped studies."
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
        "termination_context": _termination_context(package.clinical_trials),
        "risk_assessment_inputs": _risk_assessment_inputs(package.clinical_trials),
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


def _industry_landscape_payload(
    package: DiseaseReportPackage,
    *,
    stratum_counts: dict[str, int],
) -> dict[str, Any]:
    trials = package.clinical_trials
    return {
        "disease_name": package.disease_profile.disease_name,
        "canonical_condition": package.disease_profile.canonical_condition,
        "retained_count": package.source_audit.retained_count,
        "stratum_counts": stratum_counts,
        "phase_distribution": _phase_distribution(trials),
        "status_distribution": dict(Counter(trial.status for trial in trials)),
        "results_distribution": dict(Counter(trial.study_results for trial in trials)),
        "top_sponsors": _top_values([trial.sponsor for trial in trials], limit=8),
        "top_interventions": _top_values(
            [
                intervention
                for trial in trials
                for intervention in trial.interventions
            ],
            limit=12,
        ),
        "termination_context": _termination_context(trials),
        "future_outlook_constraints": [
            "Differentiate dataset-supported trial facts from broader industry interpretation.",
            "Discuss clinical differentiation, safety management, diagnostic access, operating complexity, and adoption or payment constraints only at industry level.",
            "Do not invent asset-specific reasons beyond supplied trial fields.",
        ],
    }


def _termination_context(trials: list[ClinicalTrialRecord]) -> dict[str, Any]:
    terminal_statuses = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}
    records = []
    for trial in trials:
        status = (trial.status or "").strip().upper()
        if status not in terminal_statuses:
            continue
        records.append(
            {
                "nct_number": trial.nct_number,
                "study_title": trial.study_title,
                "status": trial.status,
                "why_stopped": trial.why_stopped or "Source does not report a stop reason.",
                "sponsor": trial.sponsor,
                "interventions": list(trial.interventions),
                "phases": list(trial.phases),
            }
        )
    return {
        "terminated_like_count": len(records),
        "records": records,
        "missing_reason_count": sum(
            1
            for record in records
            if record["why_stopped"] == "Source does not report a stop reason."
        ),
    }


def _risk_assessment_inputs(trials: list[ClinicalTrialRecord], limit: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "candidate_or_intervention": ", ".join(trial.interventions) or trial.study_title,
            "sponsor": trial.sponsor,
            "status": trial.status,
            "why_stopped": trial.why_stopped,
            "phases": list(trial.phases),
            "has_results": trial.has_results,
            "study_results": trial.study_results,
            "enrollment": trial.enrollment,
            "primary_outcome_measures": list(trial.primary_outcome_measures),
            "conditions": list(trial.conditions),
        }
        for trial in trials[:limit]
    ]


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
        "why_stopped": trial.why_stopped,
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
