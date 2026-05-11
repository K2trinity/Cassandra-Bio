from __future__ import annotations

import app as app_module
from app import app


class FakeWorkflowService:
    def __init__(self, report_dir):
        self.stream_calls = []
        self.markdown_path = report_dir / "target-mode.md"
        self.html_path = report_dir / "target-mode.html"
        self.pdf_path = report_dir / "target-mode.pdf"
        self.markdown_path.write_text("# Target mode report\nBody", encoding="utf-8")
        self.html_path.write_text("<h1>Target mode report</h1>", encoding="utf-8")
        self.pdf_path.write_bytes(b"%PDF-1.4\n")

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        yield "writer", {
            "status": "writer_complete",
            "final_report": "# Target mode report\nBody",
            "final_report_markdown": "# Target mode report\nBody",
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
            "final_report": "# Target mode report\nBody",
            "final_report_markdown": "# Target mode report\nBody",
            "final_report_path": str(self.markdown_path),
            "final_report_html_path": str(self.html_path),
            "final_report_pdf_path": str(self.pdf_path),
            "clinical_data": {},
            "evidence_stats": {},
            "extension_payloads": {},
            "harvested_data": [],
            "disease_areas": [],
        }


def render_investigation() -> str:
    response = app.test_client().get("/investigation")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_investigation_page_exposes_operator_workflow_regions():
    html = render_investigation()

    for marker in [
        'data-testid="investigation-workbench"',
        'data-testid="analysis-input-panel"',
        'data-testid="workflow-summary-panel"',
        'data-testid="workflow-timeline"',
        'data-testid="live-log-panel"',
        'data-testid="result-summary-panel"',
    ]:
        assert marker in html

    for stage_id in ["collect", "handoff", "write"]:
        assert f'data-stage-id="{stage_id}"' in html


def test_investigation_page_exposes_target_mode_controls():
    html = render_investigation()

    assert 'data-testid="analysis-target-mode"' in html
    assert 'name="analysis_target_type"' in html
    assert 'value="disease"' in html
    assert 'value="company"' in html
    assert "Disease landscape" in html
    assert "Company pipeline" in html


def test_investigation_submit_sends_target_mode_form_data():
    html = render_investigation()

    assert "analysis_target_type" in html
    assert "formData.append('analysis_target_type'" in html


def test_company_quick_query_selects_company_mode():
    html = render_investigation()

    assert 'data-query="Company pipeline for Vertex Pharmaceuticals"' in html
    assert 'data-target-type="company"' in html
    assert "btn.dataset.targetType" in html


def test_investigation_quick_queries_use_supported_target_prompts():
    html = render_investigation()

    assert 'placeholder="conduct a comprehensive survey on Alzheimer Disease"' in html
    assert 'data-query="conduct a comprehensive survey on Alzheimer Disease"' in html
    assert 'data-target-type="disease"' in html
    assert "Alzheimer Disease landscape" in html
    assert 'data-query="Company pipeline for Vertex Pharmaceuticals"' in html
    assert 'data-target-type="company"' in html
    assert "Vertex pipeline" in html
    assert html.count('class="quick-query ') == 2
    assert "Melanoma safety landscape" not in html
    assert "CRISPR disease landscape" not in html
    assert 'data-query="Assess nivolumab hepatotoxicity in melanoma patients"' not in html
    assert 'data-query="Evaluate CRISPR off-target effects in clinical trials"' not in html


def test_investigation_page_exposes_prompt_pattern_guide_for_both_report_types():
    html = render_investigation()

    assert 'data-testid="prompt-pattern-guide"' in html
    assert "View prompt patterns" in html
    assert "Disease report" in html
    assert "conduct a comprehensive survey on Alzheimer Disease" in html
    assert "Company report" in html
    assert "Company pipeline for Vertex Pharmaceuticals" in html


def test_investigation_warns_when_query_sentence_may_not_retrieve():
    html = render_investigation()

    assert 'id="promptWarning"' in html
    assert "function getPromptPatternWarning" in html
    assert "This sentence may not retrieve ClinicalTrials records" in html
    assert "Use: conduct a comprehensive survey on Alzheimer Disease" in html
    assert "Use: Company pipeline for Vertex Pharmaceuticals" in html
    assert "queryInput.addEventListener('input', updatePromptWarning)" in html
    assert "analysis_target_type" in html


def test_analyze_empty_harvest_payload_explains_source_problem(monkeypatch, tmp_path):
    fake_service = FakeWorkflowService(tmp_path)
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)

    response = app.test_client().post(
        "/api/analyze",
        json={
            "query": "Evaluate CRISPR off-target effects in clinical trials",
            "analysis_target_type": "disease",
        },
    )

    assert response.status_code == 202
    thread = app_module.active_analysis["thread"]
    thread.join(timeout=10)

    payload = app_module.active_analysis["result_payload"]
    assert payload["empty_source_guidance"]["status"] == "empty_source"
    assert "prompt/target mismatch" in payload["empty_source_guidance"]["likely_issue"]
    assert "Disease landscape on <disease>" in payload["empty_source_guidance"]["actions"][0]
    assert "source_audit" in payload


def test_investigation_completion_renders_empty_source_guidance():
    html = render_investigation()

    assert "function buildEmptySourceGuidanceHtml" in html
    assert "No ClinicalTrials records were retained" in html
    assert "data.empty_source_guidance" in html


def test_investigation_kline_navigation_preserves_current_run_page():
    html = render_investigation()

    assert 'href="/kline" target="_blank" rel="noopener noreferrer" data-tab="kline"' in html


def test_investigation_page_has_no_graph_or_image_capture_remnants():
    html = render_investigation()

    for removed in [
        "Neo4j",
        "Knowledge Graph",
        "ForceGraph",
        "currentImagePanel",
        "loadDrugSubgraph",
        "figure_evidence",
        "Figures:",
        "Enter Research Query",
    ]:
        assert removed not in html


def test_analyze_accepts_json_target_mode_and_forwards_to_workflow(monkeypatch, tmp_path):
    fake_service = FakeWorkflowService(tmp_path)
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)

    response = app.test_client().post(
        "/api/analyze",
        json={
            "query": "Analyze Vertex Pharmaceuticals clinical pipeline",
            "analysis_target_type": "company",
        },
    )

    assert response.status_code == 202
    thread = app_module.active_analysis["thread"]
    thread.join(timeout=10)

    assert fake_service.stream_calls[0]["analysis_target_type"] == "company"
    assert app_module.active_analysis["analysis_target_type"] == "company"
    assert app_module.active_analysis["result_payload"]["analysis_target_type"] == "company"


def test_analyze_accepts_form_target_mode_and_forwards_to_workflow(monkeypatch, tmp_path):
    fake_service = FakeWorkflowService(tmp_path)
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)

    response = app.test_client().post(
        "/api/analyze",
        data={
            "query": "Analyze Alzheimer disease landscape",
            "analysis_target_type": "disease",
        },
    )

    assert response.status_code == 202
    thread = app_module.active_analysis["thread"]
    thread.join(timeout=10)

    assert fake_service.stream_calls[0]["analysis_target_type"] == "disease"


def test_analyze_rejects_invalid_target_mode(monkeypatch, tmp_path):
    fake_service = FakeWorkflowService(tmp_path)
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)

    response = app.test_client().post(
        "/api/analyze",
        json={
            "query": "Analyze Alzheimer disease landscape",
            "analysis_target_type": "portfolio",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid analysis_target_type"
    assert fake_service.stream_calls == []
