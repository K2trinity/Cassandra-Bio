from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.reports.disease.models import DiseaseReportArtifacts
from src.reports.disease.orchestrator import DiseaseReportOrchestrator


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
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "conduct a disease report on Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
    )

    assert state["status"] == "writer_complete"
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

    assert [record["nct_number"] for record in state["clinical_data"]["trial_records"]] == ["NCT_ALZHEIMER"]
    assert len(state["clinical_data"]["raw_records"]) == 1
    assert state["clinical_data"]["rejected_records"] == ["NCT_PARKINSON"]
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
