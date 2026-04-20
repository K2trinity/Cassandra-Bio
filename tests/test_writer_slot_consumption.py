"""Verify writer_node passes extension slot data through to the report agent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from src.agents.report_writer import ReportOutput
from src.graph.nodes.writer_node import writer_node


def _make_state_with_slots():
    return {
        "user_query": "Lung cancer drug landscape",
        "harvested_data": [
            {"title": "Study A", "summary": "OS 12 months", "source": "PubMed", "pmid": "1", "metadata": {}},
        ],
        "harvest_data_layers": {"disease_layer": {}},
        "harvest_source_payloads": {},
        "harvest_frontend_payload": {},
        "extension_payloads": {
            "slot_a": {
                "evidence_synthesis": {
                    "evidence_layers": {"rct": [{"title": "Study A"}]},
                    "grade_scores": {"overall": "B", "score": 3.5},
                }
            },
            "slot_b": {
                "clinical_analysis": {
                    "pipeline_matrix": [{"indication": "NSCLC", "intervention": "Drug X"}],
                    "safety_signals": [],
                }
            },
            "slot_c": {
                "quality_assessment": {
                    "confidence_grade": "B",
                    "confidence_score": 0.72,
                    "rationale": "Acceptable quality.",
                }
            },
        },
        "pdf_paths": [],
        "project_name": "TestProject",
        "dataflow_contract_version": "2026-04-17.v4",
    }


@patch("src.graph.nodes.writer_node.create_report_agent")
@patch("src.graph.nodes.writer_node.build_biomedical_profile")
def test_writer_passes_all_slots_as_synthesis_sections(mock_profile, mock_agent_factory):
    mock_profile.return_value = {
        "disease_areas": [], "drug_baselines": [], "target_signals": [],
        "company_entities": [], "clinical_data": {}, "evidence_stats": {},
    }

    mock_output = MagicMock()
    mock_output.markdown_content = "# Test Report"
    mock_output.markdown_path = "/tmp/test.md"

    mock_agent = MagicMock()
    mock_agent.write_report.return_value = mock_output
    mock_agent_factory.return_value = mock_agent

    state = _make_state_with_slots()
    result = writer_node(state)

    assert result["status"] == "writer_complete"

    call_kwargs = mock_agent.write_report.call_args[1]
    synthesis = call_kwargs["synthesis_sections"]
    assert "slot_a" in synthesis
    assert "slot_b" in synthesis
    assert "slot_c" in synthesis
    assert "evidence_synthesis" in synthesis["slot_a"]
    assert "clinical_analysis" in synthesis["slot_b"]
    assert "quality_assessment" in synthesis["slot_c"]


@patch("src.graph.nodes.writer_node.create_report_agent")
@patch("src.graph.nodes.writer_node.build_biomedical_profile")
def test_writer_includes_analysis_status_with_extensions(mock_profile, mock_agent_factory):
    mock_profile.return_value = {
        "disease_areas": [], "drug_baselines": [], "target_signals": [],
        "company_entities": [], "clinical_data": {}, "evidence_stats": {},
    }

    mock_output = MagicMock()
    mock_output.markdown_content = "# Report"
    mock_output.markdown_path = None

    mock_agent = MagicMock()
    mock_agent.write_report.return_value = mock_output
    mock_agent_factory.return_value = mock_agent

    state = _make_state_with_slots()
    result = writer_node(state)

    call_kwargs = mock_agent.write_report.call_args[1]
    assert call_kwargs["analysis_status"] == "FULL_PIPELINE"


@patch("src.graph.nodes.writer_node.create_report_agent")
@patch("src.graph.nodes.writer_node.build_biomedical_profile")
def test_writer_returns_html_and_pdf_artifact_paths(mock_profile, mock_agent_factory):
    mock_profile.return_value = {
        "disease_areas": [], "drug_baselines": [], "target_signals": [],
        "company_entities": [], "clinical_data": {}, "evidence_stats": {},
    }

    mock_agent = MagicMock()
    mock_agent.write_report.return_value = ReportOutput(
        markdown_content="# Report",
        markdown_path="final_reports/test.md",
        html_path="final_reports/test.html",
        pdf_path="final_reports/test.pdf",
    )
    mock_agent_factory.return_value = mock_agent

    result = writer_node(_make_state_with_slots())

    assert result["final_report_html_path"] == "final_reports/test.html"
    assert result["final_report_pdf_path"] == "final_reports/test.pdf"


if __name__ == "__main__":
    test_writer_passes_all_slots_as_synthesis_sections()
    print("[PASS] test_writer_passes_all_slots_as_synthesis_sections")
    test_writer_includes_analysis_status_with_extensions()
    print("[PASS] test_writer_includes_analysis_status_with_extensions")
    print("Writer slot consumption tests complete.")
