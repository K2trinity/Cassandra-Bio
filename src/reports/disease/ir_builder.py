from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.engines.report_engine.core import DocumentComposer

from .landscape import stratum_counts
from .models import (
    ClinicalTrialRecord,
    DiseaseChapterNarratives,
    DiseaseReportPackage,
    PipelineRiskRecord,
)

LANDSCAPE_COLUMNS = [
    "Layer",
    "Study Title",
    "NCT Number",
    "Phase",
    "Status",
    "Results",
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
    {"key": "study_title", "width": "18%"},
    {"key": "nct_number", "width": "10%"},
    {"key": "phases", "width": "8%"},
    {"key": "status", "width": "9%"},
    {"key": "study_results", "width": "9%"},
    {"key": "interventions", "width": "12%"},
    {"key": "sponsor", "width": "10%"},
    {"key": "enrollment", "width": "6%"},
    {"key": "primary_outcome_measures", "width": "14%"},
    {"key": "last_update_posted", "width": "8%"},
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
        disease_name = package.disease_profile.disease_name
        metadata = {
            "title": f"{disease_name} Disease Report",
            "reportType": "single-disease-report",
            "disease": {
                "name": disease_name,
                "canonicalCondition": package.disease_profile.canonical_condition,
                "query": package.disease_profile.query,
                "conditionTerms": list(package.disease_profile.condition_terms),
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
                    }
                ]
            },
        }
        chapters = [
            self._executive_summary_chapter(package, narratives),
            self._landscape_chapter(package.clinical_trials, narratives),
            self._risk_chapter(package.risk_records, narratives),
        ]

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
        trials: list[ClinicalTrialRecord],
        narratives: DiseaseChapterNarratives,
    ) -> dict:
        rows = [
            [
                _layer_memberships(trial),
                trial.study_title,
                trial.nct_number,
                _join_list(trial.phases),
                trial.status,
                trial.study_results,
                _join_list(trial.interventions),
                trial.sponsor,
                trial.enrollment,
                _join_list(trial.primary_outcome_measures),
                trial.last_update_posted,
            ]
            for trial in trials
        ]
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
                    _layer_summary_rows(trials),
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


def _layer_summary_rows(trials: list[ClinicalTrialRecord]) -> list[list[Any]]:
    counts = stratum_counts(trials)
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


def _trial_has_stratum(trial: ClinicalTrialRecord, stratum: str) -> bool:
    memberships = trial.strata or [trial.primary_stratum or "unclassified"]
    return stratum in memberships


def _heading(text: str, anchor: str) -> dict:
    return {"type": "heading", "level": 2, "text": text, "anchor": anchor}


def _paragraph(text: Any) -> dict:
    return {"type": "paragraph", "inlines": [{"text": _display_value(text)}]}


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


def _layer_memberships(trial: ClinicalTrialRecord) -> str:
    return _join_list(trial.strata) if trial.strata else trial.primary_stratum


def _display_value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, (date, datetime)):
        return _isoformat(value)
    return str(value)


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
