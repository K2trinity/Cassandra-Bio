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
    DiseaseChapterNarratives,
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
        phases=["PHASE1"],
        has_results=False,
        study_results="No posted results",
        enrollment=500,
        primary_outcome_measures=["Change in iADRS"],
        strata=["frontier"],
        primary_stratum="frontier",
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
    if chapter_id == "clinical_trial_and_pipeline_landscape":
        return next(
            block
            for block in chapter["blocks"]
            if block["type"] == "table"
            and block["caption"] == "Clinical trial landscape"
            and block["metadata"]["layout"] == "wide-clinical-trial-table"
        )
    return next(
        block
        for block in chapter["blocks"]
        if block["type"] == "table"
    )


def test_ir_has_exact_three_approved_chapters():
    ir = DiseaseReportIRBuilder().build(_package())

    assert [chapter["title"] for chapter in ir["chapters"]] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]


def test_landscape_table_uses_layer_phase_status_results_columns():
    ir = DiseaseReportIRBuilder().build(_package())

    chapter = next(
        chapter
        for chapter in ir["chapters"]
        if chapter["chapterId"] == "clinical_trial_and_pipeline_landscape"
    )
    tables = [block for block in chapter["blocks"] if block["type"] == "table"]

    assert tables[0]["caption"] == "ClinicalTrials landscape layer summary"
    assert tables[1]["caption"] == "Clinical trial landscape"
    assert _table_headers(tables[1]) == LANDSCAPE_COLUMNS
    assert tables[1]["metadata"]["layout"] == "wide-clinical-trial-table"
    assert tables[1]["metadata"]["className"] == "clinical-trial-landscape"
    assert len(tables[1]["colgroup"]) == len(LANDSCAPE_COLUMNS)
    assert "Layer" in LANDSCAPE_COLUMNS
    assert "Phase" in LANDSCAPE_COLUMNS
    assert "Results" in LANDSCAPE_COLUMNS


def test_landscape_table_renders_source_fields_without_llm_rewrite():
    ir = DiseaseReportIRBuilder().build(_package())

    table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    values = [
        cell["blocks"][0]["inlines"][0]["text"]
        for cell in table["rows"][1]["cells"]
    ]

    assert "frontier" in values
    assert "PHASE1" in values
    assert "RECRUITING" in values
    assert "No posted results" in values
    assert "Change in iADRS" in values


def test_landscape_table_renders_all_layer_memberships():
    package = _package()
    trial = package.clinical_trials[0].model_copy(
        update={
            "strata": ["evidence", "foundation"],
            "primary_stratum": "evidence",
        }
    )
    package = package.model_copy(update={"clinical_trials": [trial]})

    ir = DiseaseReportIRBuilder().build(package)

    table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    layer_cell = table["rows"][1]["cells"][0]
    layer_value = layer_cell["blocks"][0]["inlines"][0]["text"]

    assert layer_value == "evidence, foundation"


def test_ir_excludes_removed_sections_and_removed_fields():
    ir = DiseaseReportIRBuilder().build(_package())

    payload = json.dumps(ir, ensure_ascii=False)

    for removed_text in [
        " ".join(["Drug", "Pipeline"]),
        " ".join(["Trial", "Landscape"]),
        " ".join(["Company", "Technical", "Route", "Analysis"]),
        " ".join(["Literature", "Review"]),
        " ".join(["CNS", "Benchmark"]),
        " ".join(["Data", "Quality"]),
        " ".join(["Primary", "Endpoint"]),
    ]:
        assert removed_text not in payload


def test_risk_table_consumes_pipeline_risk_record_values():
    ir = DiseaseReportIRBuilder().build(_package())

    table = _find_table(ir, "pipeline_timeline_and_competition_risk")
    first_data_row = table["rows"][1]["cells"]
    values = [cell["blocks"][0]["inlines"][0]["text"] for cell in first_data_row]

    assert _table_headers(table) == RISK_COLUMNS
    assert table["metadata"]["layout"] == "wide-risk-table"
    assert table["metadata"]["className"] == "pipeline-risk"
    assert len(table["colgroup"]) == len(RISK_COLUMNS)
    assert [column["key"] for column in table["colgroup"]] == [
        "study_title",
        "nct_number",
        "sponsor",
        "status",
        "intervention_category",
        "timeline_signal",
        "timeline_evidence",
        "competition_signal",
        "competition_evidence",
    ]
    assert all(len(row["cells"]) == len(RISK_COLUMNS) for row in table["rows"])
    assert {
        entry["chapterId"]
        for entry in ir["metadata"]["layout"]["wideTables"]
    } == {
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
    }
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


def test_ir_builder_inserts_narrative_paragraphs_without_changing_tables():
    narratives = DiseaseChapterNarratives(
        executive_summary="中文执行摘要段落。",
        clinical_trial_and_pipeline_landscape="中文管线格局段落。",
        pipeline_timeline_and_competition_risk="中文风险段落。",
        language="zh",
    )

    ir = DiseaseReportIRBuilder().build(_package(), narratives=narratives)

    chapters = {chapter["chapterId"]: chapter for chapter in ir["chapters"]}
    assert chapters["executive_summary"]["blocks"][1]["inlines"][0]["text"] == "中文执行摘要段落。"
    assert (
        chapters["clinical_trial_and_pipeline_landscape"]["blocks"][1]["inlines"][0]["text"]
        == "中文管线格局段落。"
    )
    assert (
        chapters["pipeline_timeline_and_competition_risk"]["blocks"][1]["inlines"][0]["text"]
        == "中文风险段落。"
    )

    landscape_table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    risk_table = _find_table(ir, "pipeline_timeline_and_competition_risk")
    assert _table_headers(landscape_table) == LANDSCAPE_COLUMNS
    assert _table_headers(risk_table) == RISK_COLUMNS
