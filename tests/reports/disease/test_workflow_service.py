from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.reports.disease.models import DiseaseChapterNarratives, DiseaseReportArtifacts
from src.reports.disease.orchestrator import DiseaseReportOrchestrator
from src.services.workflow_service import WorkflowService


def _study(nct: str, condition: str, status: str = "RECRUITING") -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": nct,
                "briefTitle": f"{condition} study {nct}",
            },
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": "2024-01-15"},
                "lastUpdatePostDateStruct": {"date": "2026-04-01"},
            },
            "conditionsModule": {"conditions": [condition]},
            "armsInterventionsModule": {
                "interventions": [{"name": "Amyloid monoclonal antibody"}],
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": f"Sponsor {nct}"},
            },
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }


class FakeRendererAdapter:
    def render_all(
        self,
        document_ir: Any,
        output_dir: str | Path,
        project_name: str,
    ) -> DiseaseReportArtifacts:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        base_name = project_name.replace(" ", "_")
        markdown_path = output_path / f"{base_name}.md"
        html_path = output_path / f"{base_name}.html"
        pdf_path = output_path / f"{base_name}.pdf"
        ir_path = output_path / f"{base_name}.ir.json"

        markdown = f"# {project_name}\n"
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(f"<h1>{project_name}</h1>", encoding="utf-8")
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


class FakeNarrativeService:
    def __init__(self):
        self.calls = []

    def generate(self, package, language: str = "zh"):
        self.calls.append({"package": package, "language": language})
        return DiseaseChapterNarratives(
            executive_summary="English narrative.",
            clinical_trial_and_pipeline_landscape="English landscape.",
            pipeline_timeline_and_competition_risk="English risk.",
            language="en" if language == "en" else "zh",
        )


class FakeOrchestrator:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    def run(
        self,
        *,
        user_query: str,
        output_dir: str,
        narrative_language: str = "zh",
    ) -> dict[str, Any]:
        self.run_calls.append(
            {
                "user_query": user_query,
                "output_dir": output_dir,
                "narrative_language": narrative_language,
            }
        )
        return {
            "status": "writer_complete",
            "user_query": user_query,
            "output_dir": output_dir,
        }

    def stream(
        self,
        *,
        user_query: str,
        output_dir: str,
        narrative_language: str = "zh",
    ):
        self.stream_calls.append(
            {
                "user_query": user_query,
                "output_dir": output_dir,
                "narrative_language": narrative_language,
            }
        )
        for node_name in ["harvester", "extension_handoff", "writer"]:
            yield node_name, {
                "status": f"{node_name}_complete",
                "user_query": user_query,
                "output_dir": output_dir,
            }


def test_orchestrator_run_returns_app_state_keys(tmp_path):
    studies = [
        _study("NCT_ALZHEIMER", "Alzheimer's Disease"),
        _study("NCT_PARKINSON", "Parkinson Disease"),
    ]

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"studies": studies}

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        narrative_service=EmptyNarrativeService(),
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a disease report on Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
    )

    assert state["status"] == "writer_complete"
    assert state["handoff_complete"] is True
    assert state["writer_complete"] is True
    assert state["user_query"] == "conduct a disease report on Alzheimer disease"
    assert state["project_name"] == "Alzheimer Disease"
    assert state["analysis_focus"] == "DISEASE_REPORT_PIPELINE"
    assert state["disease_areas"] == ["Alzheimer Disease"]
    assert state["errors"] == []
    assert state["extension_payloads"] == {}

    assert len(state["harvested_data"]) == 1
    harvested = state["harvested_data"][0]
    assert harvested["source"] == "clinicaltrials.gov"
    assert harvested["title"] == "Alzheimer's Disease study NCT_ALZHEIMER"
    assert harvested["nct_id"] == "NCT_ALZHEIMER"
    assert harvested["nct_number"] == "NCT_ALZHEIMER"
    assert harvested["conditions"] == ["Alzheimer's Disease"]
    assert harvested["url"] == "https://clinicaltrials.gov/study/NCT_ALZHEIMER"
    assert harvested["metadata"]["study_first_posted"] == "2024-01-15"

    assert state["clinical_data"]["trial_records"] == 1
    assert state["clinical_data"]["raw_records"] == 1
    assert state["clinical_data"]["rejected_records"] == 1
    assert [
        record["nct_number"]
        for record in state["clinical_data"]["trial_record_details"]
    ] == ["NCT_ALZHEIMER"]
    assert len(state["clinical_data"]["raw_record_details"]) == 1
    assert state["clinical_data"]["rejected_nct_numbers"] == ["NCT_PARKINSON"]
    assert state["evidence_stats"] == {"clinical_trial_records": 1}

    package = state["disease_report_package"]
    assert package["disease_profile"]["disease_name"] == "Alzheimer Disease"
    assert [trial["nct_number"] for trial in package["clinical_trials"]] == ["NCT_ALZHEIMER"]

    assert state["final_report"] == "# Alzheimer Disease\n"
    assert state["final_report_markdown"] == "# Alzheimer Disease\n"
    assert Path(state["final_report_path"]).exists()
    assert Path(state["final_report_html_path"]).exists()
    assert Path(state["final_report_pdf_path"]).exists()
    assert Path(state["final_report_ir_path"]).exists()
    assert state["report_ir"]["metadata"]["disease"]["name"] == "Alzheimer Disease"


def test_orchestrator_stream_yields_harvest_handoff_writer_nodes(tmp_path):
    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"studies": [_study("NCT_ALZHEIMER", "Alzheimer Disease")]}

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        narrative_service=EmptyNarrativeService(),
        current_date_for_tests="2026-04-27",
    )

    events = list(
        orchestrator.stream(
            "Alzheimer disease",
            output_dir=tmp_path,
            max_trials=50,
        )
    )

    assert [node_name for node_name, state in events] == [
        "harvester",
        "extension_handoff",
        "writer",
    ]
    handoff_state = events[1][1]
    writer_state = events[2][1]
    assert handoff_state["handoff_complete"] is True
    assert writer_state["handoff_complete"] is True
    assert writer_state["writer_complete"] is True


def test_workflow_service_run_uses_disease_orchestrator(tmp_path):
    orchestrator = FakeOrchestrator()
    service = WorkflowService(
        orchestrator_factory=lambda: orchestrator,
        output_dir=tmp_path,
    )

    state = service.run(
        "Alzheimer disease",
        pdf_paths=["ignored.pdf"],
        checkpointer=object(),
        thread_id="ignored-thread",
    )

    assert state["status"] == "writer_complete"
    assert state["user_query"] == "Alzheimer disease"
    assert state["output_dir"] == str(tmp_path)
    assert orchestrator.run_calls == [
        {
            "user_query": "Alzheimer disease",
            "output_dir": str(tmp_path),
            "narrative_language": "zh",
        }
    ]


def test_workflow_service_stream_uses_three_public_progress_nodes(tmp_path):
    orchestrator = FakeOrchestrator()
    progress_events: list[tuple[str, dict[str, Any]]] = []
    service = WorkflowService(
        orchestrator_factory=lambda: orchestrator,
        output_dir=tmp_path,
    )

    events = list(
        service.stream(
            "Alzheimer disease",
            pdf_paths=["ignored.pdf"],
            progress_callback=lambda node_name, state: progress_events.append((node_name, state)),
            checkpointer=object(),
            thread_id="ignored-thread",
            interrupt_before=["ignored"],
            allow_interrupts=True,
        )
    )

    node_names = [node_name for node_name, state in events]
    assert node_names == ["harvester", "extension_handoff", "writer"]
    assert progress_events == events
    assert orchestrator.stream_calls == [
        {
            "user_query": "Alzheimer disease",
            "output_dir": str(tmp_path),
            "narrative_language": "zh",
        }
    ]
    assert not {
        "disease" + "_survey" + "_intelligence",
        "evidence" + "_synthesizer",
        "clinical" + "_analyzer",
        "quality" + "_assessor",
    }.intersection(node_names)


def test_orchestrator_passes_narrative_language_to_service(tmp_path):
    narrative_service = FakeNarrativeService()

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"studies": [_study("NCT_ALZHEIMER", "Alzheimer Disease")]}

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        narrative_service=narrative_service,
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
        narrative_language="en",
    )

    assert narrative_service.calls[0]["language"] == "en"
    assert state["disease_report_narratives"]["language"] == "en"
    assert state["report_ir"]["chapters"][0]["blocks"][1]["inlines"][0]["text"] == "English narrative."


def test_workflow_service_forwards_narrative_language(tmp_path):
    class LanguageOrchestrator(FakeOrchestrator):
        def run(
            self,
            *,
            user_query: str,
            output_dir: str,
            narrative_language: str = "zh",
        ) -> dict[str, Any]:
            return {
                "status": "writer_complete",
                "user_query": user_query,
                "output_dir": output_dir,
                "narrative_language": narrative_language,
            }

    orchestrator = LanguageOrchestrator()
    service = WorkflowService(orchestrator_factory=lambda: orchestrator, output_dir=tmp_path)

    state = service.run("Alzheimer disease", narrative_language="en")

    assert state["narrative_language"] == "en"
