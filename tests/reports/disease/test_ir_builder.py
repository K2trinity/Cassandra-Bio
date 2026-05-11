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

RISK_ASSESSMENT_COLUMNS = [
    "Candidate / Sponsor",
    "Mechanism Or Intervention",
    "Clinical Stage / Status",
    "Clinical Evidence Snapshot",
    "Safety And Clinical Risk Cue",
    "Operational And Commercial Risk Cue",
]


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
        phases=["PHASE1"],
        has_results=False,
        study_results="No posted results",
        enrollment=500,
        primary_outcome_measures=["Change in iADRS"],
        strata=["frontier"],
        primary_stratum="frontier",
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
        details={
            "target_type": "disease",
            "stratum_counts": {
                "evidence": 0,
                "foundation": 0,
                "frontier": 1,
                "unclassified": 0,
            },
        },
    )
    return DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 27, 8, 30, tzinfo=timezone.utc),
    )


def _company_package() -> DiseaseReportPackage:
    package = _package()
    company_profile = package.disease_profile.model_copy(
        update={
            "query": "Company pipeline for Vertex Pharmaceuticals",
            "target_type": "company",
            "target_name": "Vertex Pharmaceuticals",
            "company_name": "Vertex Pharmaceuticals",
            "disease_name": "Vertex Pharmaceuticals",
            "canonical_condition": "Vertex Pharmaceuticals",
            "condition_terms": [],
            "normalized_terms": [],
        }
    )
    catalyst_trial = package.clinical_trials[0].model_copy(
        update={
            "phases": ["PHASE3"],
            "has_results": True,
            "study_results": "Results available",
            "primary_stratum": "catalyst",
            "strata": ["catalyst"],
        }
    )
    expansion_trial = package.clinical_trials[0].model_copy(
        update={
            "nct_number": "NCT00000002",
            "study_title": "Recruiting acute pain study",
            "conditions": ["Acute Pain"],
            "primary_stratum": "expansion",
            "strata": ["expansion"],
            "study_results": "No posted results",
        }
    )
    track_record_trial = package.clinical_trials[0].model_copy(
        update={
            "nct_number": "NCT00000003",
            "study_title": "Posted results study",
            "conditions": ["Cystic Fibrosis"],
            "primary_stratum": "track_record",
            "strata": ["track_record"],
            "study_results": "Results available",
        }
    )
    company_audit = package.source_audit.model_copy(
        update={
            "retained_count": 3,
            "details": {
                "target_type": "company",
                "target_name": "Vertex Pharmaceuticals",
                "company_name": "Vertex Pharmaceuticals",
                "stratum_counts": {"catalyst": 1, "expansion": 1, "track_record": 1},
                "expansion_condition_counts": {"Acute Pain": 1},
            },
        }
    )
    return package.model_copy(
        update={
            "disease_profile": company_profile,
            "clinical_trials": [catalyst_trial, expansion_trial, track_record_trial],
            "source_audit": company_audit,
        }
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
    return next(block for block in chapter["blocks"] if block["type"] == "table")


def _table_rows(table: dict) -> list[list[str]]:
    return [
        [
            cell["blocks"][0]["inlines"][0]["text"]
            for cell in row["cells"]
        ]
        for row in table["rows"][1:]
    ]


def _chapter(ir: dict, chapter_id: str) -> dict:
    return next(chapter for chapter in ir["chapters"] if chapter["chapterId"] == chapter_id)


def _block_text(block: dict) -> str:
    payload = json.dumps(block, ensure_ascii=False)
    return payload


def _widget_titles(chapter: dict) -> list[str]:
    titles = []
    for block in chapter["blocks"]:
        if block.get("type") == "widget":
            props = block.get("props") if isinstance(block.get("props"), dict) else {}
            titles.append(props.get("title") or block.get("title") or "")
    return titles


def test_disease_ir_has_four_isolated_chapters():
    ir = DiseaseReportIRBuilder().build(_package())

    assert [chapter["title"] for chapter in ir["chapters"]] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
        "Disease Evidence Synthesis Summary",
    ]
    assert ir["chapters"][-1]["chapterId"] == "disease_evidence_synthesis_summary"
    assert "companyPipeline" not in ir["metadata"]
    assert ir["metadata"]["disease"]["targetType"] == "disease"


def test_landscape_table_uses_layer_phase_status_results_columns():
    ir = DiseaseReportIRBuilder().build(_package())
    chapter = _chapter(ir, "clinical_trial_and_pipeline_landscape")
    tables = [block for block in chapter["blocks"] if block["type"] == "table"]

    assert tables[0]["caption"] == "ClinicalTrials landscape layer summary"
    assert tables[1]["caption"] == "Clinical trial landscape"
    assert _table_headers(tables[1]) == LANDSCAPE_COLUMNS
    assert "Layer" in LANDSCAPE_COLUMNS
    assert "Phase" in LANDSCAPE_COLUMNS
    assert "Status" in LANDSCAPE_COLUMNS
    assert "Results" in LANDSCAPE_COLUMNS
    assert "Stop Reason" in LANDSCAPE_COLUMNS
    assert len(tables[1]["colgroup"]) == len(LANDSCAPE_COLUMNS)


def test_layer_summary_includes_unclassified_stratum_count():
    package = _package()
    unclassified = package.clinical_trials[0].model_copy(
        update={
            "nct_number": "NCT_UNCLASSIFIED",
            "study_title": "Observational source record",
            "phases": ["NA"],
            "status": "UNKNOWN",
            "strata": ["unclassified"],
            "primary_stratum": "unclassified",
            "has_results": True,
        }
    )
    package = package.model_copy(update={"clinical_trials": [unclassified]})

    ir = DiseaseReportIRBuilder().build(package)
    chapter = _chapter(ir, "clinical_trial_and_pipeline_landscape")
    summary_table = next(
        block
        for block in chapter["blocks"]
        if block["type"] == "table"
        and block["caption"] == "ClinicalTrials landscape layer summary"
    )
    rows = _table_rows(summary_table)

    assert [
        "Unclassified",
        "1",
        "Records outside configured evidence/foundation/frontier filters",
        "1",
        "Retained source records without configured layer assignment",
    ] in rows


def test_landscape_table_renders_source_fields_without_llm_rewrite():
    ir = DiseaseReportIRBuilder().build(_package())
    table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    values = [
        cell["blocks"][0]["inlines"][0]["text"]
        for cell in table["rows"][1]["cells"]
    ]

    assert _table_headers(table) == LANDSCAPE_COLUMNS
    assert "Frontier" in values
    assert "PHASE1" in values
    assert "RECRUITING" in values
    assert "No posted results" in values
    assert "-" in values
    assert "Change in iADRS" in values


def test_landscape_table_renders_all_layer_memberships_as_labels():
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
    layer_value = table["rows"][1]["cells"][0]["blocks"][0]["inlines"][0]["text"]

    assert layer_value == "Evidence, Foundation"


def test_company_ir_exposes_pipeline_condition_counts_and_company_fourth_summary():
    narratives = DiseaseChapterNarratives(
        company_catalyst_and_rd_summary=(
            "**Catalyst Tracker:** one near-term event. "
            "**Expansion Map:** Acute Pain leads recruiting focus. "
            "**Track Record:** posted results are evidence, not success-rate proof."
        )
    )

    ir = DiseaseReportIRBuilder().build(_company_package(), narratives=narratives)

    assert ir["metadata"]["companyPipeline"] == {
        "stratumCounts": {"catalyst": 1, "expansion": 1, "track_record": 1},
        "expansionConditionCounts": {"Acute Pain": 1},
    }
    assert [chapter["title"] for chapter in ir["chapters"]] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
        "Company Catalyst And R&D Summary",
    ]
    chapter = ir["chapters"][-1]
    assert chapter["chapterId"] == "company_catalyst_and_rd_summary"
    assert chapter["blocks"][1]["type"] == "callout"
    assert "**Catalyst Tracker:** one near-term event." in _block_text(chapter["blocks"][1])
    bold_labels = [
        inline["text"]
        for block in chapter["blocks"]
        for inline in block.get("inlines", [])
        if {"type": "bold"} in inline.get("marks", [])
    ]
    assert bold_labels == ["Catalyst Tracker", "Expansion Map", "Track Record"]


def test_company_landscape_uses_company_layer_labels():
    ir = DiseaseReportIRBuilder().build(_company_package())
    table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    rows = _table_rows(table)

    assert rows[0][0] == "Catalyst Tracker"
    assert rows[1][0] == "Expansion Map"
    assert rows[2][0] == "Track Record"
    assert "PHASE3" in rows[0]
    assert "Results available" in rows[0]


def test_disease_ir_appends_disease_fourth_summary_without_company_labels():
    narratives = DiseaseChapterNarratives(
        disease_evidence_synthesis_summary="前三章共同总结疾病证据，不使用公司管线标签。",
        industry_landscape_summary="Industry Landscape Summary: 该疾病行业仍由疗效分化、诊断分层和支付约束共同驱动。",
    )

    ir = DiseaseReportIRBuilder().build(_package(), narratives=narratives)
    chapter = ir["chapters"][-1]
    payload = json.dumps(chapter, ensure_ascii=False)

    assert chapter["chapterId"] == "disease_evidence_synthesis_summary"
    assert "前三章共同总结疾病证据" in payload
    assert "Industry Landscape Summary" in payload
    assert "Catalyst Tracker" not in payload
    assert "Expansion Map" not in payload
    assert "Track Record" not in payload


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
        disease_evidence_synthesis_summary="中文前三章总结段落。",
        language="zh",
    )

    ir = DiseaseReportIRBuilder().build(_package(), narratives=narratives)

    chapters = {chapter["chapterId"]: chapter for chapter in ir["chapters"]}
    assert chapters["executive_summary"]["blocks"][1]["type"] == "callout"
    assert "中文执行摘要段落。" in _block_text(chapters["executive_summary"]["blocks"][1])
    assert chapters["clinical_trial_and_pipeline_landscape"]["blocks"][1]["type"] == "callout"
    assert "中文管线格局段落。" in _block_text(
        chapters["clinical_trial_and_pipeline_landscape"]["blocks"][1]
    )
    assert chapters["pipeline_timeline_and_competition_risk"]["blocks"][1]["type"] == "callout"
    assert "中文风险段落。" in _block_text(chapters["pipeline_timeline_and_competition_risk"]["blocks"][1])
    assert chapters["disease_evidence_synthesis_summary"]["blocks"][1]["type"] == "callout"
    assert "中文前三章总结段落。" in _block_text(
        chapters["disease_evidence_synthesis_summary"]["blocks"][1]
    )

    landscape_table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    risk_table = _find_table(ir, "pipeline_timeline_and_competition_risk")
    assert _table_headers(landscape_table) == LANDSCAPE_COLUMNS
    assert _table_headers(risk_table) == RISK_COLUMNS


def test_ir_builder_adds_one_glance_visual_overview():
    ir = DiseaseReportIRBuilder().build(_package())
    executive = _chapter(ir, "executive_summary")

    assert ir["metadata"]["layout"]["visualHierarchy"] == [
        "chapterBrief",
        "kpiGrid",
        "chart",
        "summaryTable",
        "detailTable",
    ]
    assert executive["blocks"][1]["type"] == "callout"
    assert executive["blocks"][1]["title"] == "Chapter Brief"
    assert _widget_titles(executive) == [
        "Report Intake Funnel",
        "Landscape Layer Mix",
    ]
    intake_chart = next(
        block
        for block in executive["blocks"]
        if block.get("type") == "widget"
        and block.get("widgetId") == "report-intake-funnel"
    )
    assert intake_chart["data"]["labels"] == ["Retained Records", "Rejected Records"]
    assert intake_chart["data"]["datasets"][0]["data"] == [1, 2]


def test_landscape_chapter_surfaces_charts_before_drilldown_tables():
    ir = DiseaseReportIRBuilder().build(_company_package())
    chapter = _chapter(ir, "clinical_trial_and_pipeline_landscape")
    widgets = [block for block in chapter["blocks"] if block.get("type") == "widget"]
    first_table_index = next(
        index for index, block in enumerate(chapter["blocks"]) if block.get("type") == "table"
    )

    assert [widget["widgetId"] for widget in widgets] == [
        "landscape-layer-mix",
        "landscape-phase-mix",
        "landscape-results-availability",
        "landscape-status-mix",
    ]
    assert max(chapter["blocks"].index(widget) for widget in widgets) < first_table_index
    assert widgets[0]["data"]["labels"] == [
        "Catalyst Tracker",
        "Expansion Map",
        "Track Record",
    ]
    assert widgets[0]["data"]["datasets"][0]["data"] == [1, 1, 1]


def test_risk_and_final_summary_chapters_have_data_hierarchy_charts():
    ir = DiseaseReportIRBuilder().build(_package())
    risk = _chapter(ir, "pipeline_timeline_and_competition_risk")
    final_summary = _chapter(ir, "disease_evidence_synthesis_summary")

    assert _widget_titles(risk) == [
        "Timeline Signal Distribution",
        "Competition Signal Distribution",
    ]
    assert _widget_titles(final_summary) == [
        "Disease Evidence Hierarchy",
        "Report Evidence Flow",
    ]
    timeline_chart = next(
        block
        for block in risk["blocks"]
        if block.get("widgetId") == "risk-timeline-signal-distribution"
    )
    assert timeline_chart["data"]["labels"] == ["Low"]
    assert timeline_chart["data"]["datasets"][0]["data"] == [1]


def test_landscape_and_fourth_chapter_explain_terminated_trial_context():
    package = _package()
    terminated = ClinicalTrialRecord(
        study_title="Terminated Alzheimer Disease asset study",
        nct_number="NCT_TERMINATED",
        status="TERMINATED",
        conditions=["Alzheimer Disease"],
        interventions=["Asset X"],
        sponsor="Sponsor X",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2021, 1, 15),
        phases=["PHASE2"],
        has_results=False,
        study_results="No posted results",
        enrollment=160,
        primary_outcome_measures=["Change in cognition score"],
        strata=["foundation"],
        primary_stratum="foundation",
        why_stopped="Business decision after interim portfolio review.",
        source_url="https://clinicaltrials.gov/study/NCT_TERMINATED",
    )
    package = package.model_copy(
        update={
            "clinical_trials": [package.clinical_trials[0], terminated],
            "source_audit": package.source_audit.model_copy(
                update={
                    "retained_count": 2,
                    "details": {
                        "target_type": "disease",
                        "stratum_counts": {
                            "evidence": 0,
                            "foundation": 1,
                            "frontier": 1,
                            "unclassified": 0,
                        },
                    },
                }
            ),
        }
    )
    narratives = DiseaseChapterNarratives(
        disease_evidence_synthesis_summary="前三章显示该疾病管线既有前沿探索，也有终止项目需要解释。",
        industry_landscape_summary="Industry Landscape Summary: 阿尔茨海默病行业未来仍取决于疗效分化、安全性管理、诊断准入和支付路径。",
    )

    ir = DiseaseReportIRBuilder().build(package, narratives=narratives)
    landscape_table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    terminated_row = next(
        row
        for row in _table_rows(landscape_table)
        if "NCT_TERMINATED" in row
    )
    assert "Business decision after interim portfolio review." in terminated_row

    final_summary = _chapter(ir, "disease_evidence_synthesis_summary")
    assessment_table = next(
        block
        for block in final_summary["blocks"]
        if block.get("type") == "table"
        and block.get("caption") == "Multidimensional clinical and commercial risk assessment"
    )
    assert _table_headers(assessment_table) == RISK_ASSESSMENT_COLUMNS
    assessment_rows = _table_rows(assessment_table)
    terminated_assessment = next(row for row in assessment_rows if "Asset X" in row[0])
    assert "TERMINATED" in terminated_assessment[2]
    assert "Business decision after interim portfolio review." in terminated_assessment[5]
    assert "Industry Landscape Summary" in _block_text(final_summary)
