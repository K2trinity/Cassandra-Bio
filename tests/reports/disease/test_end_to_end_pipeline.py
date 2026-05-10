from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.engines.report_engine.renderers.markdown_renderer import MarkdownRenderer
from src.reports.disease.models import DiseaseReportArtifacts
from src.reports.disease.orchestrator import DiseaseReportOrchestrator


def _study(
    nct: str,
    condition: str,
    *,
    title: str,
    status: str,
    intervention: str,
    first_posted: str,
    phases: list[str] | None = None,
    has_results: bool = False,
) -> dict[str, Any]:
    return {
        "hasResults": has_results,
        "protocolSection": {
            "identificationModule": {
                "nctId": nct,
                "briefTitle": title,
            },
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": first_posted},
                "lastUpdatePostDateStruct": {"date": "2026-04-01"},
            },
            "conditionsModule": {"conditions": [condition]},
            "armsInterventionsModule": {
                "interventions": [{"name": intervention}],
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": f"Sponsor {nct}"},
            },
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": phases or [],
                "enrollmentInfo": {"count": 100},
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Primary endpoint measure"}],
            },
        }
    }


class CapturingRendererAdapter:
    def __init__(self) -> None:
        self.document_ir: dict[str, Any] | None = None
        self.chapter_titles: list[str] = []

    def render_all(
        self,
        document_ir: dict[str, Any],
        output_dir: str | Path,
        project_name: str,
    ) -> DiseaseReportArtifacts:
        self.document_ir = document_ir
        self.chapter_titles = [
            str(chapter.get("title", ""))
            for chapter in document_ir.get("chapters", [])
        ]

        markdown = MarkdownRenderer().render(document_ir)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        base_name = project_name.replace(" ", "_")
        markdown_path = output_path / f"{base_name}.md"
        html_path = output_path / f"{base_name}.html"
        pdf_path = output_path / f"{base_name}.pdf"
        ir_path = output_path / f"{base_name}.ir.json"

        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(f"<pre>{markdown}</pre>", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4\n")
        ir_path.write_text(json.dumps(document_ir, default=str), encoding="utf-8")

        return DiseaseReportArtifacts(
            markdown_content=markdown,
            markdown_path=str(markdown_path),
            html_path=str(html_path),
            pdf_path=str(pdf_path),
            ir_path=str(ir_path),
        )


def test_disease_report_pipeline_filters_and_renders_merged_shape(tmp_path):
    retained_recruiting = "NCT_ALZ_RECRUITING"
    retained_completed = "NCT_ALZ_COMPLETED"
    rejected_parkinson = "NCT_PARKINSON_TITLE_ONLY"
    rejected_cognitive = "NCT_COGNITIVE_CBT"
    studies = [
        _study(
            retained_recruiting,
            "Alzheimer Disease",
            title="Amyloid antibody in Alzheimer Disease",
            status="RECRUITING",
            intervention="Amyloid monoclonal antibody",
            first_posted="2026-01-15",
            phases=["PHASE1"],
            has_results=False,
        ),
        _study(
            retained_completed,
            "Alzheimer's Disease",
            title="Tau therapy for Alzheimer's Disease",
            status="COMPLETED",
            intervention="Tau aggregation inhibitor",
            first_posted="2025-10-10",
            phases=["PHASE3"],
            has_results=True,
        ),
        _study(
            rejected_parkinson,
            "Parkinson Disease",
            title="Alzheimer biomarker monitoring in Parkinson Disease",
            status="RECRUITING",
            intervention="Digital biomarker monitoring",
            first_posted="2026-02-01",
        ),
        _study(
            rejected_cognitive,
            "Cognitive Impairment",
            title="CBT for cognitive impairment",
            status="COMPLETED",
            intervention="Cognitive Behavioral Therapy",
            first_posted="2025-08-15",
        ),
    ]

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"studies": studies}

    renderer = CapturingRendererAdapter()
    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=renderer,
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a comprehensive survey on Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
    )

    assert state["status"] == "writer_complete"
    assert state["clinical_data"]["trial_records"] == 2

    final_report = state["final_report"]
    assert retained_recruiting in final_report
    assert retained_completed in final_report
    assert "RECRUITING" in final_report
    assert "COMPLETED" in final_report
    assert rejected_parkinson not in final_report
    assert rejected_cognitive not in final_report
    assert "frontier" in final_report
    assert "evidence" in final_report
    assert "foundation" in final_report
    assert "PHASE1" in final_report
    assert "PHASE3" in final_report
    assert "Results available" in final_report
    assert "No posted results" in final_report

    assert state["clinical_data"]["rejected_nct_numbers"] == [
        rejected_parkinson,
        rejected_cognitive,
    ]
    assert [
        record["nct_number"]
        for record in state["clinical_data"]["trial_record_details"]
    ] == [
        retained_recruiting,
        retained_completed,
    ]
    trial_details = state["clinical_data"]["trial_record_details"]
    by_nct = {record["nct_number"]: record for record in trial_details}
    assert by_nct[retained_recruiting]["primary_stratum"] == "frontier"
    assert by_nct[retained_completed]["primary_stratum"] == "evidence"
    assert by_nct[retained_completed]["strata"] == ["evidence", "foundation"]

    clinical_chapter = next(
        chapter
        for chapter in state["report_ir"]["chapters"]
        if chapter["chapterId"] == "clinical_trial_and_pipeline_landscape"
    )
    assert any(
        block.get("type") == "table"
        and block.get("caption") == "ClinicalTrials landscape layer summary"
        for block in clinical_chapter["blocks"]
    )

    for old_section in [
        " ".join(["Drug", "Pipeline"]),
        " ".join(["Trial", "Landscape"]),
        " ".join(["Company", "Technical", "Route", "Analysis"]),
        " ".join(["Literature", "Review"]),
        " ".join(["CNS", "Benchmark"]),
        " ".join(["Data", "Quality"]),
    ]:
        assert old_section not in final_report

    for removed_field in [" ".join(["Primary", "Endpoint"])]:
        assert removed_field not in final_report

    assert renderer.chapter_titles == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]
    assert [
        chapter["title"]
        for chapter in state["report_ir"]["chapters"]
    ] == renderer.chapter_titles
    assert Path(state["final_report_path"]).exists()
    assert Path(state["final_report_html_path"]).exists()
    assert Path(state["final_report_pdf_path"]).exists()
    assert Path(state["final_report_ir_path"]).exists()
