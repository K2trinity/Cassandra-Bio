# Disease Survey IR Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the disease survey report path so Cassandra produces structured IR-backed disease reports with LLM synthesis, chart widgets, and concrete HTML/PDF outputs instead of markdown-only fallback output.

**Architecture:** Keep the existing disease survey aggregator and section renderers as the deterministic base, then add one unified composition layer that produces markdown, IR, HTML, PDF, and audit metadata together. Wire `writer_node`, `ReportWriterAgent`, `AgentState`, and `app.py` to consume this single result object so the app only falls back to markdown when no IR artifacts were generated.

**Tech Stack:** Python, pytest, Flask, existing report engine IR/HTML/PDF renderers, existing report LLM client

---

### Task 1: Lock failing tests for the broken contract

**Files:**
- Modify: `tests/test_disease_survey_composer.py`
- Modify: `tests/test_report_writer_agent.py`
- Modify: `tests/test_writer_slot_consumption.py`
- Test: `tests/test_disease_survey_composer.py`
- Test: `tests/test_report_writer_agent.py`
- Test: `tests/test_writer_slot_consumption.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_disease_survey_document_includes_chart_widgets():
    document = build_disease_survey_document(make_state())
    widget_blocks = [
        block
        for chapter in document["chapters"]
        for block in chapter.get("blocks", [])
        if block.get("type") == "widget"
    ]
    assert widget_blocks, "expected at least one chart widget block in IR document"


def test_write_report_returns_ir_artifact_paths(tmp_path):
    agent = ReportWriterAgent()
    result = agent.write_report(
        user_query="Alzheimer disease landscape",
        harvest_data={"results": SAMPLE_ROWS},
        project_name="AD Landscape",
        output_dir=str(tmp_path),
    )
    assert result.html_path
    assert result.pdf_path


def test_writer_node_returns_final_report_html_and_pdf_paths(mock_build_profile, mock_create_agent):
    mock_create_agent.return_value.write_report.return_value = ReportOutput(
        markdown_content="# title",
        markdown_path="final_reports/report.md",
        html_path="final_reports/report.html",
        pdf_path="final_reports/report.pdf",
    )
    result = writer_node({"user_query": "x", "harvested_data": [], "pdf_paths": [], "extension_payloads": {}})
    assert result["final_report_html_path"].endswith(".html")
    assert result["final_report_pdf_path"].endswith(".pdf")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_disease_survey_composer.py tests/test_report_writer_agent.py tests/test_writer_slot_consumption.py -v`

Expected: FAIL because the current disease composer emits `data` blocks instead of widget-backed IR, and the writer path does not return HTML/PDF artifact paths.

- [ ] **Step 3: Write minimal implementation**

```python
class ReportOutput:
    html_path: Optional[str] = None
    pdf_path: Optional[str] = None


return {
    "final_report_html_path": html_path,
    "final_report_pdf_path": pdf_path,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_disease_survey_composer.py tests/test_report_writer_agent.py tests/test_writer_slot_consumption.py -v`

Expected: PASS


### Task 2: Lock failing tests for markdown fallback parsing

**Files:**
- Modify: `tests/test_chart_rendering.py`
- Create: `tests/test_markdown_fallback_rendering.py`
- Test: `tests/test_markdown_fallback_rendering.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_html_renderer_render_from_markdown_renders_headings_and_table():
    renderer = HTMLRenderer()
    html = renderer.render_from_markdown(
        "# Title\n\n## Section\n\n| A | B |\n| --- | --- |\n| 1 | 2 |",
        title="Fallback",
        query="Fallback",
    )
    assert "<h1" in html
    assert "<table" in html


def test_pdf_renderer_render_markdown_to_file_uses_rendered_markdown_structure(tmp_path):
    renderer = PDFRenderer()
    html = renderer.html_renderer.render_from_markdown("# Title\n\nParagraph", title="X", query="Y")
    assert "<h1" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_markdown_fallback_rendering.py -v`

Expected: FAIL because the current markdown fallback wraps the whole markdown blob into a single paragraph block.

- [ ] **Step 3: Write minimal implementation**

```python
html_body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "toc"])
document_ir = markdown_to_ir(markdown_text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_markdown_fallback_rendering.py -v`

Expected: PASS


### Task 3: Lock failing tests for aggregator backfill and audit metadata

**Files:**
- Modify: `tests/test_disease_survey_aggregator.py`
- Modify: `tests/test_disease_survey_e2e.py`
- Test: `tests/test_disease_survey_aggregator.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_aggregate_backfills_intervention_and_sponsor_from_alternate_metadata_keys():
    rows = [{
        "source": "ClinicalTrials",
        "nct_id": "NCT001",
        "title": "Trial",
        "metadata": {
            "interventions": "Drug A",
            "trial_sponsor": "Company A",
            "phase": "Phase 2",
        },
    }]
    state = aggregate_survey_data(rows, "query")
    assert state.drug_assets[0].asset_name == "Drug A"
    assert state.sponsors[0].company_name == "Company A"


def test_aggregate_records_field_completeness_audit():
    state = aggregate_survey_data(AD_ROWS, "query")
    assert state.audit_metadata["missing_asset_count"] >= 0
    assert "missing_sponsor_count" in state.audit_metadata
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_disease_survey_aggregator.py tests/test_disease_survey_e2e.py -v`

Expected: FAIL because the aggregator only reads `intervention` and `sponsor`, and the state has no audit metadata.

- [ ] **Step 3: Write minimal implementation**

```python
intervention = _first_text(meta, "intervention", "interventions", "drug", "asset_name")
sponsor = _first_text(meta, "sponsor", "lead_sponsor", "trial_sponsor", "sponsor_name")
audit_metadata = {
    "missing_asset_count": missing_asset_count,
    "missing_sponsor_count": missing_sponsor_count,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_disease_survey_aggregator.py tests/test_disease_survey_e2e.py -v`

Expected: PASS


### Task 4: Implement unified disease survey composition result

**Files:**
- Modify: `src/engines/report_engine/disease_survey/models.py`
- Modify: `src/engines/report_engine/disease_survey/aggregator.py`
- Modify: `src/engines/report_engine/disease_survey/renderer.py`
- Modify: `src/engines/report_engine/disease_survey/composer.py`
- Test: `tests/test_disease_survey_composer.py`
- Test: `tests/test_disease_survey_renderer.py`

- [ ] **Step 1: Write the failing test for unified output**

```python
def test_compose_disease_survey_report_bundle_contains_markdown_ir_and_artifacts(tmp_path):
    result = compose_disease_survey_report_bundle(make_state(), output_dir=tmp_path)
    assert result["markdown"]
    assert result["document_ir"]["chapters"]
    assert result["html_path"].endswith(".html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_disease_survey_composer.py -v`

Expected: FAIL because `compose_disease_survey_report_bundle` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def compose_disease_survey_report_bundle(state, output_dir, llm_client=None):
    sections = compose_disease_survey_report(state)
    document_ir = build_disease_survey_document(state)
    markdown = disease_survey_to_markdown(state)
    return {
        "sections": sections,
        "document_ir": document_ir,
        "markdown": markdown,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_disease_survey_composer.py -v`

Expected: PASS


### Task 5: Route writer and state through the unified disease result

**Files:**
- Modify: `src/graph/state.py`
- Modify: `src/graph/nodes/writer_node.py`
- Modify: `src/agents/report_writer.py`
- Modify: `src/agents/supervisor.py`
- Test: `tests/test_writer_slot_consumption.py`
- Test: `tests/test_report_writer_agent.py`

- [ ] **Step 1: Write the failing test for state contract**

```python
def test_initial_state_contains_report_artifact_paths():
    state = _initial_state("query")
    assert "final_report_html_path" in state
    assert "final_report_pdf_path" in state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_writer_agent.py tests/test_writer_slot_consumption.py -v`

Expected: FAIL because the state and writer return payload do not include HTML/PDF keys.

- [ ] **Step 3: Write minimal implementation**

```python
final_report_html_path: Optional[str]
final_report_pdf_path: Optional[str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_writer_agent.py tests/test_writer_slot_consumption.py -v`

Expected: PASS


### Task 6: Add LLM synthesis and chart repair hook

**Files:**
- Modify: `src/engines/report_engine/disease_survey/composer.py`
- Modify: `src/engines/report_engine/utils/chart_repair_api.py`
- Test: `tests/test_disease_survey_composer.py`
- Test: `tests/test_chart_rendering.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_compose_bundle_includes_analysis_metadata_without_mocking_stats():
    result = compose_disease_survey_report_bundle(make_state(), output_dir=tmp_path, llm_client=FakeLLM())
    assert result["analysis_metadata"]["model_name"] == "fake-llm"
    assert result["analysis_metadata"]["summary_source"] == "llm"


def test_create_llm_repair_functions_returns_callable_when_client_available(monkeypatch):
    monkeypatch.setattr("src.engines.report_engine.utils.chart_repair_api.create_report_client", lambda: object())
    functions = create_llm_repair_functions()
    assert functions
    assert callable(functions[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_disease_survey_composer.py tests/test_chart_rendering.py -v`

Expected: FAIL because there is no LLM analysis metadata and the chart repair hook always returns an empty list.

- [ ] **Step 3: Write minimal implementation**

```python
def create_llm_repair_functions():
    client = create_report_client()
    return [lambda payload, context: _repair_chart_payload(client, payload, context)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_disease_survey_composer.py tests/test_chart_rendering.py -v`

Expected: PASS


### Task 7: Verify app fallback and end-to-end disease report path

**Files:**
- Modify: `app.py`
- Modify: `tests/test_disease_survey_e2e.py`
- Create: `tests/test_markdown_fallback_rendering.py`
- Test: `tests/test_disease_survey_e2e.py`
- Test: `tests/test_markdown_fallback_rendering.py`

- [ ] **Step 1: Write the failing end-to-end test**

```python
def test_e2e_writer_report_output_contains_html_pdf_and_markdown(tmp_path):
    agent = ReportWriterAgent()
    result = agent.write_report(
        user_query="Alzheimer disease pipeline",
        harvest_data={"results": AD_ROWS},
        project_name="AD",
        output_dir=str(tmp_path),
    )
    assert result.markdown_path
    assert result.html_path
    assert result.pdf_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_disease_survey_e2e.py tests/test_markdown_fallback_rendering.py -v`

Expected: FAIL because the e2e path currently emits markdown only.

- [ ] **Step 3: Write minimal implementation**

```python
_ir_html = result.get("final_report_html_path")
_ir_pdf = result.get("final_report_pdf_path")
if _ir_html and Path(_ir_html).exists():
    html_path = _ir_html
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_disease_survey_e2e.py tests/test_markdown_fallback_rendering.py -v`

Expected: PASS


### Task 8: Final verification sweep

**Files:**
- No code changes required
- Test: `tests/test_disease_survey_aggregator.py`
- Test: `tests/test_disease_survey_renderer.py`
- Test: `tests/test_disease_survey_composer.py`
- Test: `tests/test_disease_survey_e2e.py`
- Test: `tests/test_report_writer_agent.py`
- Test: `tests/test_writer_slot_consumption.py`
- Test: `tests/test_markdown_fallback_rendering.py`

- [ ] **Step 1: Run targeted verification suite**

Run: `python -m pytest tests/test_disease_survey_aggregator.py tests/test_disease_survey_renderer.py tests/test_disease_survey_composer.py tests/test_disease_survey_e2e.py tests/test_report_writer_agent.py tests/test_writer_slot_consumption.py tests/test_markdown_fallback_rendering.py -v`

Expected: PASS

- [ ] **Step 2: Run one rendering-focused regression**

Run: `python -m pytest tests/test_chart_rendering.py -v`

Expected: PASS or a narrowed failure list unrelated to this change.
