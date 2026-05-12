from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.engines.report_engine.renderers.markdown_renderer import MarkdownRenderer
from src.reports.disease.models import DiseaseChapterNarratives, DiseaseReportArtifacts
from src.reports.disease.orchestrator import DiseaseReportOrchestrator


def _study(
    nct: str,
    condition: str,
    *,
    title: str,
    status: str,
    intervention: str,
    intervention_type: str | None = None,
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
                "interventions": [
                    {
                        "name": intervention,
                        **({"type": intervention_type} if intervention_type else {}),
                    }
                ],
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


def _company_study(
    nct: str,
    condition: str,
    *,
    title: str,
    status: str,
    intervention: str,
    intervention_type: str | None = "DRUG",
    first_posted: str,
    phase: str,
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
                "primaryCompletionDateStruct": {"date": "2026-07-15"},
                "resultsFirstPostDateStruct": {"date": "2025-12-10"} if has_results else {},
            },
            "conditionsModule": {"conditions": [condition]},
            "armsInterventionsModule": {
                "interventions": [
                    {
                        "name": intervention,
                        **({"type": intervention_type} if intervention_type else {}),
                    }
                ],
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Vertex Pharmaceuticals"},
            },
            "designModule": {
                "phases": [phase],
                "studyType": "INTERVENTIONAL",
            },
        },
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


class EmptyNarrativeService:
    def generate(self, package, language: str = "zh"):
        _ = package
        return DiseaseChapterNarratives(language="en" if language == "en" else "zh")


class CompanyNarrativeService:
    def generate(self, package, language: str = "zh"):
        _ = package
        return DiseaseChapterNarratives(
            company_catalyst_and_rd_summary=(
                "**Catalyst Tracker:** event-driven readout focus. "
                "**Expansion Map:** recruiting studies show R&D allocation. "
                "**Track Record:** posted results provide historical evidence."
            ),
            language="en" if language == "en" else "zh",
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
        narrative_service=EmptyNarrativeService(),
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
    assert "Frontier" in final_report
    assert "Evidence" in final_report
    assert "Foundation" in final_report
    assert "PHASE1" in final_report
    assert "PHASE3" in final_report
    assert "Results available" in final_report
    assert "No posted results" in final_report

    assert state["clinical_data"]["rejected_nct_numbers"] == [
        rejected_parkinson,
        rejected_cognitive,
    ]
    package_nct_numbers = [
        trial["nct_number"]
        for trial in state["disease_report_package"]["clinical_trials"]
    ]
    assert [
        record["nct_number"]
        for record in state["clinical_data"]["trial_record_details"]
    ] == package_nct_numbers
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
        "Disease Evidence Synthesis Summary",
    ]
    assert "Company Catalyst And R&D Summary" not in final_report
    assert [
        chapter["title"]
        for chapter in state["report_ir"]["chapters"]
    ] == renderer.chapter_titles
    assert Path(state["final_report_path"]).exists()
    assert Path(state["final_report_html_path"]).exists()
    assert Path(state["final_report_pdf_path"]).exists()
    assert Path(state["final_report_ir_path"]).exists()


def test_company_pipeline_uses_sponsor_layers_without_disease_filtering(tmp_path):
    calls: list[dict[str, Any]] = []
    catalyst_nct = "NCT_VERTEX_CATALYST"
    expansion_nct = "NCT_VERTEX_EXPANSION"
    track_record_nct = "NCT_VERTEX_RESULTS"

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(params))
        assert params["query.spons"] == "Vertex Pharmaceuticals"
        if params.get("filter.overallStatus") == "ACTIVE_NOT_RECRUITING":
            return {
                "studies": [
                    _company_study(
                        catalyst_nct,
                        "Sickle Cell Disease",
                        title="Vertex late-stage readout study",
                        status="ACTIVE_NOT_RECRUITING",
                        intervention="VX catalyst therapy",
                        first_posted="2025-01-01",
                        phase="PHASE2",
                    ),
                    _company_study(
                        track_record_nct,
                        "Cystic Fibrosis",
                        title="Vertex result-bearing catalyst study",
                        status="ACTIVE_NOT_RECRUITING",
                        intervention="VX results therapy",
                        first_posted="2024-05-01",
                        phase="PHASE3",
                        has_results=True,
                    ),
                ]
            }
        if params.get("filter.overallStatus") == "RECRUITING":
            return {
                "studies": [
                    _company_study(
                        expansion_nct,
                        "Acute Pain",
                        title="Vertex recruiting expansion study",
                        status="RECRUITING",
                        intervention="VX expansion therapy",
                        first_posted="2026-02-01",
                        phase="PHASE1",
                    ),
                ]
            }
        if params.get("filter.advanced") == "AREA[HasResults]true":
            return {
                "studies": [
                    _company_study(
                        track_record_nct,
                        "Cystic Fibrosis",
                        title="Vertex result-bearing catalyst study",
                        status="ACTIVE_NOT_RECRUITING",
                        intervention="VX results therapy",
                        first_posted="2024-05-01",
                        phase="PHASE3",
                        has_results=True,
                    ),
                ]
            }
        return {"studies": []}

    renderer = CapturingRendererAdapter()
    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=renderer,
        narrative_service=CompanyNarrativeService(),
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a comprehensive survey on Vertex Pharmaceuticals",
        analysis_target_type="company",
        output_dir=tmp_path,
        max_trials=80,
    )

    assert state["status"] == "writer_complete"
    assert state["analysis_focus"] == "COMPANY_CLINICALTRIALS_PIPELINE"
    assert state["project_name"] == "Vertex Pharmaceuticals"
    assert state["biomedical_profile"]["target_type"] == "company"
    assert state["biomedical_profile"]["company_name"] == "Vertex Pharmaceuticals"
    assert state["clinical_data"]["trial_records"] == 3
    assert state["clinical_data"]["rejected_records"] == 0
    assert state["clinical_data"]["rejected_nct_numbers"] == []

    assert [call["query.spons"] for call in calls] == [
        "Vertex Pharmaceuticals",
        "Vertex Pharmaceuticals",
        "Vertex Pharmaceuticals",
    ]
    assert [call["pageSize"] for call in calls] == [30, 50, 30]
    assert [call.get("sort") for call in calls] == [
        "PrimaryCompletionDate:asc",
        "StudyFirstPostDate:desc",
        "LastUpdatePostDate:desc",
    ]

    final_report = state["final_report"]
    assert catalyst_nct in final_report
    assert expansion_nct in final_report
    assert track_record_nct in final_report
    assert "Sickle Cell Disease" in final_report
    assert "Acute Pain" in final_report
    assert "Catalyst Tracker" in final_report
    assert "Expansion Map" in final_report
    assert "Track Record" in final_report
    assert "Company Catalyst And R&D Summary" in final_report
    assert "**Catalyst Tracker:**" in final_report
    assert "**Expansion Map:**" in final_report
    assert "**Track Record:**" in final_report
    assert "PHASE3" in final_report
    assert "Results available" in final_report

    profile = state["disease_report_package"]["disease_profile"]
    assert profile["target_type"] == "company"
    assert profile["company_name"] == "Vertex Pharmaceuticals"
    assert state["report_ir"]["metadata"]["disease"]["targetType"] == "company"
    assert {
        record["intervention_category"]
        for record in state["disease_report_package"]["risk_records"]
    } == {"drug"}


def test_disease_pipeline_uses_clinicaltrials_intervention_type_for_named_drug(tmp_path):
    nct_number = "NCT_DISEASE_DRUG_TYPE"
    studies = [
        _study(
            nct_number,
            "Alzheimer Disease",
            title="Named asset in Alzheimer Disease",
            status="RECRUITING",
            intervention="Donanemab",
            intervention_type="DRUG",
            first_posted="2026-01-15",
            phases=["PHASE2"],
        ),
    ]

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=lambda url, params: {"studies": studies},
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=CapturingRendererAdapter(),
        narrative_service=EmptyNarrativeService(),
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a comprehensive survey on Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
    )

    risk_records = state["disease_report_package"]["risk_records"]
    assert [record["nct_number"] for record in risk_records] == [nct_number]
    assert [record["intervention_category"] for record in risk_records] == ["drug"]


def test_company_pipeline_expands_sponsor_alias_and_defaults_to_100_records(tmp_path):
    calls: list[dict[str, Any]] = []

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(params))
        assert params["query.spons"] == "Eli Lilly and Company"
        if params.get("filter.overallStatus") != "RECRUITING":
            return {"studies": []}
        return {
            "studies": [
                _company_study(
                    f"NCT_LLY_{index:05d}",
                    "Obesity",
                    title=f"Eli Lilly expansion study {index}",
                    status="RECRUITING",
                    intervention="Lilly expansion therapy",
                    first_posted=f"2026-01-{(index % 28) + 1:02d}",
                    phase="PHASE2",
                )
                for index in range(120)
            ]
        }

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=CapturingRendererAdapter(),
        narrative_service=EmptyNarrativeService(),
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a comprehensive survey on Eli Lilly And Co",
        analysis_target_type="company",
        output_dir=tmp_path,
    )

    assert state["biomedical_profile"]["company_name"] == "Eli Lilly and Company"
    assert state["clinical_data"]["trial_records"] == 100
    assert state["disease_report_package"]["source_audit"]["retained_count"] == 100
    assert state["report_ir"]["metadata"]["companyPipeline"]["expansionConditionCounts"] == {
        "Obesity": 100,
    }
