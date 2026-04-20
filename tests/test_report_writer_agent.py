"""Tests for ReportWriterAgent disease survey routing."""
from pathlib import Path

import pytest

from src.agents.report_writer import ReportWriterAgent

SAMPLE_ROWS = [
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT01767311",
        "title": "Clarity AD — Lecanemab Phase 3",
        "summary": "Phase 3 trial of lecanemab targeting amyloid beta in early AD.",
        "metadata": {
            "intervention": "Lecanemab, anti-Aβ monoclonal antibody",
            "sponsor": "Eisai",
            "phase": "Phase 3",
            "status": "Completed",
            "enrollment": "1795",
            "primary_endpoint": "CDR-SB",
            "ae_grade3plus": "ARIA-E 12.6%",
        },
    },
    {
        "source": "PubMed",
        "pmid": "38001234",
        "title": "Lecanemab in early Alzheimer's disease",
        "summary": "Phase 3 results of lecanemab.",
        "journal": "NEJM",
        "year": 2023,
        "authors": "van Dyck CH et al.",
        "doi": "10.1056/NEJMoa2212948",
    },
]


def test_disease_survey_routing():
    agent = ReportWriterAgent()
    report = agent.run("disease_survey", SAMPLE_ROWS, query="Alzheimer's disease pipeline")
    assert "executive_summary" in report
    assert "drug_pipeline" in report
    assert "trial_landscape" in report


def test_disease_survey_empty_rows():
    agent = ReportWriterAgent()
    report = agent.run("disease_survey", [], query="test")
    assert report["executive_summary"]["total_assets"] == 0


def test_unknown_report_type_raises():
    agent = ReportWriterAgent()
    with pytest.raises((ValueError, NotImplementedError, KeyError)):
        agent.run("unknown_type", [], query="test")


def test_write_report_returns_artifact_paths_for_disease_survey():
    agent = ReportWriterAgent()
    output_dir = Path("test_output") / "report_writer_agent_artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = agent.write_report(
        user_query="Alzheimer's disease pipeline",
        harvest_data={"results": SAMPLE_ROWS},
        project_name="AD Pipeline",
        output_dir=str(output_dir),
    )

    assert result.markdown_path
    assert result.html_path
    assert result.pdf_path
