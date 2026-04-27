from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.reports.disease.ir_builder import (
    LANDSCAPE_COLUMNS,
    RISK_COLUMNS,
    DiseaseReportIRBuilder,
)
from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


def _profile() -> DiseaseProfile:
    return DiseaseProfile(
        query="Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D",
    )


def _package() -> DiseaseReportPackage:
    profile = _profile()
    trial = ClinicalTrialRecord(
        study_title="A Study of Donanemab in Early Symptomatic Alzheimer Disease",
        nct_number="NCT00000001",
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor="Eli Lilly and Company",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2026, 4, 20),
        source_url="https://clinicaltrials.gov/study/NCT00000001",
    )
    risk = PipelineRiskRecord(
        nct_number="NCT00000001",
        study_title=trial.study_title,
        sponsor=trial.sponsor,
        status=trial.status,
        intervention_category="amyloid antibody",
        timeline_signal="Low",
        timeline_evidence="Recruiting study first posted 2026-04-20.",
        competition_signal="High",
        competition_evidence="Multiple retained records share the amyloid antibody category.",
    )
    audit = SourceAudit(
        topic_url=profile.expert_topic_url,
        full_match_url=profile.expert_full_match_url,
        selected_condition_terms=profile.condition_terms,
        raw_count=3,
        retained_count=1,
        rejected_count=2,
        rejected_nct_numbers=["NCT_REJECTED_1", "NCT_REJECTED_2"],
        generated_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    return DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 27, 8, 30, tzinfo=timezone.utc),
    )


def _table_headers(table: dict) -> list[str]:
    header_row = table["rows"][0]
    return [
        cell["blocks"][0]["inlines"][0]["text"]
        for cell in header_row["cells"]
    ]


def _find_table(ir: dict, chapter_id: str) -> dict:
    chapter = next(chapter for chapter in ir["chapters"] if chapter["chapterId"] == chapter_id)
    return next(block for block in chapter["blocks"] if block["type"] == "table")


def test_ir_has_exact_three_approved_chapters():
    ir = DiseaseReportIRBuilder().build(_package())

    assert [chapter["title"] for chapter in ir["chapters"]] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]


def test_landscape_table_uses_exact_approved_columns():
    ir = DiseaseReportIRBuilder().build(_package())

    table = _find_table(ir, "clinical_trial_and_pipeline_landscape")

    assert _table_headers(table) == LANDSCAPE_COLUMNS
    assert table["metadata"]["layout"] == "wide-clinical-trial-table"
    assert table["metadata"]["className"] == "clinical-trial-landscape"
    assert len(table["colgroup"]) == 7


def test_ir_excludes_removed_sections_and_removed_fields():
    ir = DiseaseReportIRBuilder().build(_package())

    payload = json.dumps(ir, ensure_ascii=False)

    for removed_text in [
        "Drug Pipeline",
        "Trial Landscape",
        "Company Technical Route Analysis",
        "Literature Review",
        "CNS Benchmark",
        "Data Quality",
        "Enrollment",
        "Primary Endpoint",
    ]:
        assert removed_text not in payload


def test_risk_table_consumes_pipeline_risk_record_values():
    ir = DiseaseReportIRBuilder().build(_package())

    table = _find_table(ir, "pipeline_timeline_and_competition_risk")
    first_data_row = table["rows"][1]["cells"]
    values = [cell["blocks"][0]["inlines"][0]["text"] for cell in first_data_row]

    assert _table_headers(table) == RISK_COLUMNS
    assert values == [
        "A Study of Donanemab in Early Symptomatic Alzheimer Disease",
        "NCT00000001",
        "Eli Lilly and Company",
        "RECRUITING",
        "amyloid antibody",
        "Low",
        "Recruiting study first posted 2026-04-20.",
        "High",
        "Multiple retained records share the amyloid antibody category.",
    ]
