from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any

from src.engines.report_engine.core import DocumentComposer

from .landscape import stratum_counts as disease_stratum_counts
from .models import (
    ClinicalTrialRecord,
    DiseaseChapterNarratives,
    DiseaseReportPackage,
    PipelineRiskRecord,
)

STRATUM_LABELS = {
    "catalyst": "Catalyst Tracker",
    "expansion": "Expansion Map",
    "track_record": "Track Record",
    "evidence": "Evidence",
    "foundation": "Foundation",
    "frontier": "Frontier",
    "unclassified": "Unclassified",
}

LANDSCAPE_COLUMNS = [
    "Layer",
    "Study Title",
    "NCT Number",
    "Phase",
    "Status",
    "Results",
    "Conditions",
    "Interventions",
    "Sponsor",
    "Enrollment",
    "Primary Outcomes",
    "Last Update Posted",
]

RISK_COLUMNS = [
    "Study Title",
    "NCT Number",
    "Sponsor",
    "Status",
    "Intervention Category",
    "Timeline Signal",
    "Timeline Evidence",
    "Competition Signal",
    "Competition Evidence",
]

LANDSCAPE_COLGROUP = [
    {"key": "strata", "width": "8%"},
    {"key": "study_title", "width": "16%"},
    {"key": "nct_number", "width": "9%"},
    {"key": "phases", "width": "7%"},
    {"key": "status", "width": "8%"},
    {"key": "study_results", "width": "8%"},
    {"key": "conditions", "width": "10%"},
    {"key": "interventions", "width": "10%"},
    {"key": "sponsor", "width": "9%"},
    {"key": "enrollment", "width": "5%"},
    {"key": "primary_outcome_measures", "width": "14%"},
    {"key": "last_update_posted", "width": "7%"},
]

RISK_COLGROUP = [
    {"key": "study_title", "width": "18%"},
    {"key": "nct_number", "width": "10%"},
    {"key": "sponsor", "width": "12%"},
    {"key": "status", "width": "10%"},
    {"key": "intervention_category", "width": "12%"},
    {"key": "timeline_signal", "width": "9%"},
    {"key": "timeline_evidence", "width": "15%"},
    {"key": "competition_signal", "width": "9%"},
    {"key": "competition_evidence", "width": "15%"},
]


class DiseaseReportIRBuilder:
    def build(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives | None = None,
    ) -> dict:
        narratives = narratives or DiseaseChapterNarratives()
        profile = package.disease_profile
        disease_name = profile.disease_name
        target_name = profile.target_name or profile.company_name or disease_name
        is_company = profile.target_type == "company"
        metadata = {
            "title": (
                f"{target_name} ClinicalTrials Pipeline"
                if is_company
                else f"{disease_name} Disease Report"
            ),
            "reportType": "company-clinicaltrials-pipeline" if is_company else "single-disease-report",
            "disease": {
                "name": disease_name,
                "canonicalCondition": profile.canonical_condition,
                "query": profile.query,
                "conditionTerms": list(profile.condition_terms),
                "targetType": profile.target_type,
                "targetName": target_name,
                "companyName": profile.company_name,
            },
            "generatedAt": _isoformat(package.generated_at),
            "sourceAudit": package.source_audit.model_dump(mode="json"),
            "layout": {
                "wideTables": [
                    {
                        "chapterId": "clinical_trial_and_pipeline_landscape",
                        "layout": "wide-clinical-trial-table",
                        "className": "clinical-trial-landscape",
                        "columns": len(LANDSCAPE_COLUMNS),
                    },
                    {
                        "chapterId": "pipeline_timeline_and_competition_risk",
                        "layout": "wide-risk-table",
                        "className": "pipeline-risk",
                        "columns": len(RISK_COLUMNS),
                    },
                ]
            },
        }
        if is_company:
            audit_details = package.source_audit.details
            metadata["companyPipeline"] = {
                "stratumCounts": _int_mapping(audit_details.get("stratum_counts")),
                "expansionConditionCounts": _int_mapping(
                    audit_details.get("expansion_condition_counts")
                ),
            }
        else:
            metadata["diseaseLandscape"] = {
                "stratumCounts": _stratum_counts(package),
            }

        chapters = [
            self._executive_summary_chapter(package, narratives),
            self._landscape_chapter(package, narratives),
            self._risk_chapter(package.risk_records, narratives),
        ]
        if is_company:
            chapters.append(self._company_summary_chapter(package, narratives))
        else:
            chapters.append(self._disease_summary_chapter(package, narratives))

        return DocumentComposer().build_document(
            report_id=f"single-disease-report-{_slug(disease_name)}",
            metadata=metadata,
            chapters=chapters,
        )

    def _executive_summary_chapter(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        audit = package.source_audit
        latest_posted = _latest_study_first_posted(package.clinical_trials)
        summary = (
            f"{package.disease_profile.disease_name} report built from "
            f"{audit.retained_count} retained clinical trial records and "
            f"{audit.rejected_count} rejected records."
        )
        if latest_posted is not None:
            summary += f" Latest Study First Posted date is {latest_posted.isoformat()}."

        return {
            "chapterId": "executive_summary",
            "title": "Executive Summary",
            "anchor": "executive-summary",
            "order": 10,
            "blocks": [
                _heading("Executive Summary", "executive-summary"),
                _paragraph(narratives.executive_summary or summary),
                {
                    "type": "kpiGrid",
                    "cols": 3,
                    "items": [
                        {"label": "Retained Records", "value": str(audit.retained_count)},
                        {"label": "Rejected Records", "value": str(audit.rejected_count)},
                        {"label": "Risk Records", "value": str(len(package.risk_records))},
                    ],
                },
            ],
        }

    def _landscape_chapter(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        trials = package.clinical_trials
        rows = [
            [
                _display_strata(trial),
                trial.study_title,
                trial.nct_number,
                _join_list(trial.phases),
                trial.status,
                trial.study_results,
                _join_list(trial.conditions),
                _join_list(trial.interventions),
                trial.sponsor,
                trial.enrollment,
                _join_list(trial.primary_outcome_measures),
                trial.last_update_posted,
            ]
            for trial in trials
        ]
        is_company = package.disease_profile.target_type == "company"
        return {
            "chapterId": "clinical_trial_and_pipeline_landscape",
            "title": "Clinical Trial And Pipeline Landscape",
            "anchor": "clinical-trial-and-pipeline-landscape",
            "order": 20,
            "blocks": [
                _heading(
                    "Clinical Trial And Pipeline Landscape",
                    "clinical-trial-and-pipeline-landscape",
                ),
                _paragraph(
                    narratives.clinical_trial_and_pipeline_landscape
                    or f"Structured clinical landscape contains {len(trials)} retained records."
                ),
                _table(
                    ["Layer", "Records", "Filter Meaning", "With Results", "Core Question"],
                    (
                        _company_layer_summary_rows(trials)
                        if is_company
                        else _disease_layer_summary_rows(trials)
                    ),
                    caption="ClinicalTrials landscape layer summary",
                    metadata={
                        "layout": "clinical-trial-layer-summary",
                        "className": "clinical-trial-layer-summary",
                    },
                ),
                _table(
                    LANDSCAPE_COLUMNS,
                    rows,
                    caption="Clinical trial landscape",
                    metadata={
                        "layout": "wide-clinical-trial-table",
                        "className": "clinical-trial-landscape",
                    },
                    colgroup=LANDSCAPE_COLGROUP,
                ),
            ],
        }

    def _risk_chapter(
        self,
        risk_records: list[PipelineRiskRecord],
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        rows = [
            [
                record.study_title,
                record.nct_number,
                record.sponsor,
                record.status,
                record.intervention_category,
                record.timeline_signal,
                record.timeline_evidence,
                record.competition_signal,
                record.competition_evidence,
            ]
            for record in risk_records
        ]
        return {
            "chapterId": "pipeline_timeline_and_competition_risk",
            "title": "Pipeline Timeline And Competition Risk",
            "anchor": "pipeline-timeline-and-competition-risk",
            "order": 30,
            "blocks": [
                _heading(
                    "Pipeline Timeline And Competition Risk",
                    "pipeline-timeline-and-competition-risk",
                ),
                _paragraph(
                    narratives.pipeline_timeline_and_competition_risk
                    or f"Timeline and competition assessment uses {len(risk_records)} deterministic risk records."
                ),
                _table(
                    RISK_COLUMNS,
                    rows,
                    caption="Pipeline timeline and competition risk records",
                    metadata={
                        "layout": "wide-risk-table",
                        "className": "pipeline-risk",
                    },
                    colgroup=RISK_COLGROUP,
                ),
            ],
        }

    def _company_summary_chapter(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        audit_details = package.source_audit.details
        stratum_counts = _int_mapping(audit_details.get("stratum_counts"))
        expansion_condition_counts = _int_mapping(
            audit_details.get("expansion_condition_counts")
        )
        summary_text = (
            narratives.company_catalyst_and_rd_summary
            or _company_summary_fallback(stratum_counts, expansion_condition_counts)
        )
        return {
            "chapterId": "company_catalyst_and_rd_summary",
            "title": "Company Catalyst And R&D Summary",
            "anchor": "company-catalyst-and-rd-summary",
            "order": 40,
            "blocks": [
                _heading(
                    "Company Catalyst And R&D Summary",
                    "company-catalyst-and-rd-summary",
                ),
                _paragraph(summary_text),
                _labeled_paragraph(
                    "Catalyst Tracker",
                    f"{stratum_counts.get('catalyst', 0)} event-driven records prioritized by near-term readout timing.",
                ),
                _labeled_paragraph(
                    "Expansion Map",
                    _expansion_summary_text(
                        stratum_counts.get("expansion", 0),
                        expansion_condition_counts,
                    ),
                ),
                _labeled_paragraph(
                    "Track Record",
                    f"{stratum_counts.get('track_record', 0)} result-bearing records provide historical evidence, not inferred success rate.",
                ),
            ],
        }

    def _disease_summary_chapter(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        counts = _stratum_counts(package)
        summary_text = (
            narratives.disease_evidence_synthesis_summary
            or _disease_summary_fallback(package, counts)
        )
        return {
            "chapterId": "disease_evidence_synthesis_summary",
            "title": "Disease Evidence Synthesis Summary",
            "anchor": "disease-evidence-synthesis-summary",
            "order": 40,
            "blocks": [
                _heading(
                    "Disease Evidence Synthesis Summary",
                    "disease-evidence-synthesis-summary",
                ),
                _paragraph(summary_text),
                _labeled_paragraph(
                    "Evidence Base",
                    (
                        f"{counts.get('evidence', 0)} result-bearing records, "
                        f"{counts.get('foundation', 0)} foundation records, and "
                        f"{counts.get('frontier', 0)} frontier records summarize the disease landscape."
                    ),
                ),
                _labeled_paragraph(
                    "Risk Context",
                    f"{len(package.risk_records)} deterministic risk records summarize the timeline and competition chapter.",
                ),
                _labeled_paragraph(
                    "Boundary",
                    "This chapter summarizes the first three disease chapters only and does not use company-mode sponsor framing.",
                ),
            ],
        }


def _disease_layer_summary_rows(trials: list[ClinicalTrialRecord]) -> list[list[Any]]:
    counts = disease_stratum_counts(trials)
    result_counts = {
        stratum: sum(
            1
            for trial in trials
            if _trial_has_stratum(trial, stratum) and trial.has_results
        )
        for stratum in ("evidence", "foundation", "frontier", "unclassified")
    }
    return [
        [
            "Evidence",
            counts["evidence"],
            "Posted results",
            result_counts["evidence"],
            "Objective efficacy/safety result-bearing records",
        ],
        [
            "Foundation",
            counts["foundation"],
            "Phase 3/4 active-not-recruiting or completed",
            result_counts["foundation"],
            "Late-stage standard-of-care and benchmark activity",
        ],
        [
            "Frontier",
            counts["frontier"],
            "Phase 1/2 recruiting or not-yet-recruiting",
            result_counts["frontier"],
            "Early mechanism and target exploration",
        ],
        [
            "Unclassified",
            counts["unclassified"],
            "Records outside configured evidence/foundation/frontier filters",
            result_counts["unclassified"],
            "Retained source records without configured layer assignment",
        ],
    ]


def _company_layer_summary_rows(trials: list[ClinicalTrialRecord]) -> list[list[Any]]:
    counts = _generic_stratum_counts(trials)
    result_counts = {
        stratum: sum(
            1
            for trial in trials
            if _trial_has_stratum(trial, stratum) and trial.has_results
        )
        for stratum in ("catalyst", "expansion", "track_record", "unclassified")
    }
    return [
        [
            "Catalyst Tracker",
            counts.get("catalyst", 0),
            "Phase 2/3 active-not-recruiting sponsor records",
            result_counts["catalyst"],
            "Event-driven near-term readout focus",
        ],
        [
            "Expansion Map",
            counts.get("expansion", 0),
            "Recruiting sponsor records",
            result_counts["expansion"],
            "Current R&D allocation by condition",
        ],
        [
            "Track Record",
            counts.get("track_record", 0),
            "Sponsor records with posted results",
            result_counts["track_record"],
            "Result-bearing historical evidence, not inferred success rate",
        ],
        [
            "Unclassified",
            counts.get("unclassified", 0),
            "Records outside configured company layers",
            result_counts["unclassified"],
            "Retained sponsor records without configured layer assignment",
        ],
    ]


def _trial_has_stratum(trial: ClinicalTrialRecord, stratum: str) -> bool:
    memberships = trial.strata or [trial.primary_stratum or "unclassified"]
    return stratum in memberships


def _heading(text: str, anchor: str) -> dict:
    return {"type": "heading", "level": 2, "text": text, "anchor": anchor}


def _paragraph(text: Any) -> dict:
    return {"type": "paragraph", "inlines": [{"text": _display_value(text)}]}


def _labeled_paragraph(label: str, body: str) -> dict:
    return {
        "type": "paragraph",
        "inlines": [
            {"text": label, "marks": [{"type": "bold"}]},
            {"text": f": {body}"},
        ],
    }


def _table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    caption: str,
    metadata: dict[str, Any] | None = None,
    colgroup: list[dict[str, Any]] | None = None,
) -> dict:
    table_rows = [
        {
            "cells": [
                {
                    "header": True,
                    "isHeader": True,
                    "blocks": [_paragraph(header)],
                }
                for header in headers
            ]
        }
    ]
    for row in rows:
        table_rows.append(
            {
                "cells": [
                    {"blocks": [_paragraph(value)]}
                    for value in row
                ]
            }
        )

    block: dict[str, Any] = {
        "type": "table",
        "caption": caption,
        "rows": table_rows,
    }
    if metadata:
        block["metadata"] = metadata
    if colgroup:
        block["colgroup"] = colgroup
    return block


def _join_list(values: list[str]) -> str:
    return ", ".join(value for value in values if value) or "-"


def _display_strata(trial: ClinicalTrialRecord) -> str:
    values = trial.strata or [trial.primary_stratum or "unclassified"]
    labels = [STRATUM_LABELS.get(value, value) for value in values if value]
    return _join_list(labels)


def _display_value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, (date, datetime)):
        return _isoformat(value)
    return str(value)


def _stratum_counts(package: DiseaseReportPackage) -> dict[str, int]:
    counts = _int_mapping(package.source_audit.details.get("stratum_counts"))
    if counts:
        return counts
    if package.disease_profile.target_type == "company":
        return _generic_stratum_counts(package.clinical_trials)
    return disease_stratum_counts(package.clinical_trials)


def _generic_stratum_counts(trials: list[ClinicalTrialRecord]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for trial in trials:
        memberships = trial.strata or [trial.primary_stratum or "unclassified"]
        counter.update(stratum for stratum in memberships if stratum)
    return dict(counter)


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(count)
        for key, count in value.items()
        if isinstance(count, int)
    }


def _company_summary_fallback(
    stratum_counts: dict[str, int],
    expansion_condition_counts: dict[str, int],
) -> str:
    expansion_focus = _top_conditions_text(expansion_condition_counts)
    return (
        f"**Catalyst Tracker:** {stratum_counts.get('catalyst', 0)} event-driven records. "
        f"**Expansion Map:** {stratum_counts.get('expansion', 0)} recruiting records; {expansion_focus}. "
        f"**Track Record:** {stratum_counts.get('track_record', 0)} posted-results records as historical evidence."
    )


def _disease_summary_fallback(
    package: DiseaseReportPackage,
    stratum_counts: dict[str, int],
) -> str:
    return (
        f"The first three chapters retain {package.source_audit.retained_count} clinical trial records "
        f"for {package.disease_profile.disease_name}, including "
        f"{stratum_counts.get('evidence', 0)} evidence, "
        f"{stratum_counts.get('foundation', 0)} foundation, and "
        f"{stratum_counts.get('frontier', 0)} frontier records. "
        f"The risk chapter contributes {len(package.risk_records)} deterministic risk records; "
        "interpretation remains source-grounded and disease-level."
    )


def _expansion_summary_text(
    count: int,
    expansion_condition_counts: dict[str, int],
) -> str:
    return f"{count} recruiting records show current R&D allocation; {_top_conditions_text(expansion_condition_counts)}."


def _top_conditions_text(expansion_condition_counts: dict[str, int]) -> str:
    if not expansion_condition_counts:
        return "top conditions unavailable"
    top_items = list(expansion_condition_counts.items())[:3]
    return "top conditions: " + ", ".join(f"{name} ({count})" for name, count in top_items)


def _isoformat(value: date | datetime) -> str:
    return value.isoformat()


def _latest_study_first_posted(trials: list[ClinicalTrialRecord]) -> date | None:
    posted_dates = [
        trial.study_first_posted
        for trial in trials
        if trial.study_first_posted is not None
    ]
    return max(posted_dates) if posted_dates else None


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().split() if part) or "disease"


__all__ = [
    "LANDSCAPE_COLUMNS",
    "RISK_COLUMNS",
    "DiseaseReportIRBuilder",
]
