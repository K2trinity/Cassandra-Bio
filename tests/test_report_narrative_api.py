from __future__ import annotations

import app as app_module
from app import app


class FakeWorkflowService:
    def __init__(self, report_dir):
        self.stream_calls = []
        self.markdown_path = report_dir / "narrative.md"
        self.html_path = report_dir / "narrative.html"
        self.pdf_path = report_dir / "narrative.pdf"
        self.markdown_path.write_text("# Report\nNarrative text", encoding="utf-8")
        self.html_path.write_text("<h1>Report</h1>", encoding="utf-8")
        self.pdf_path.write_bytes(b"%PDF-1.4\n")

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        yield "writer", {
            "status": "writer_complete",
            "final_report": "# Report\nNarrative text",
            "final_report_markdown": "# Report\nNarrative text",
            "final_report_path": str(self.markdown_path),
            "final_report_html_path": str(self.html_path),
            "final_report_pdf_path": str(self.pdf_path),
            "clinical_data": {},
            "evidence_stats": {},
            "extension_payloads": {},
            "harvested_data": [],
            "disease_areas": [],
        }

    def run(self, **kwargs):
        return {
            "status": "writer_complete",
            "final_report": "# Report\nNarrative text",
            "final_report_markdown": "# Report\nNarrative text",
            "final_report_path": str(self.markdown_path),
            "final_report_html_path": str(self.html_path),
            "final_report_pdf_path": str(self.pdf_path),
            "clinical_data": {},
            "evidence_stats": {},
            "extension_payloads": {},
            "harvested_data": [],
            "disease_areas": [],
        }


def test_analyze_accepts_english_narrative_language(monkeypatch, tmp_path):
    fake_service = FakeWorkflowService(tmp_path)
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)
    monkeypatch.setattr(app_module, "NEO4J_AVAILABLE", False)

    client = app.test_client()
    response = client.post(
        "/api/analyze",
        json={"query": "Alzheimer disease report", "narrative_language": "en"},
    )

    assert response.status_code == 202
    thread = app_module.active_analysis["thread"]
    thread.join(timeout=10)

    assert fake_service.stream_calls[0]["narrative_language"] == "en"
    assert app_module.active_analysis["result_payload"]["narrative_language"] == "en"
