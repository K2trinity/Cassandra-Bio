# Investigation UI Workflow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cleaner Investigation research workspace after removing Neo4j graph and captured-image preview surfaces.

**Architecture:** Keep the Flask/Jinja/Tailwind runtime and Socket.IO contracts. Refactor `templates/index.html` in place around semantic workbench panels and add a rendered HTML regression test for the UI contract.

**Tech Stack:** Flask, Jinja templates, Tailwind browser runtime, Socket.IO, pytest.

---

### Task 1: Add Rendered UI Contract Test

**Files:**
- Create: `tests/test_investigation_ui.py`

- [ ] **Step 1: Write the failing test**

```python
from app import app


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_investigation_ui.py -q --basetemp .pytest_tmp_investigation_ui_tdd`

Expected: FAIL because the new semantic workbench markers do not exist yet and a few image/graph remnants still appear.

### Task 2: Refactor Investigation Markup

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Replace the old hero and stacked panels**

Keep existing IDs, but wrap the page in:

```html
<section data-testid="investigation-workbench" class="...">
  <aside data-testid="analysis-input-panel">...</aside>
  <section data-testid="workflow-summary-panel">...</section>
  <section data-testid="workflow-timeline">...</section>
  <section data-testid="live-log-panel">...</section>
  <section data-testid="result-summary-panel">...</section>
</section>
```

- [ ] **Step 2: Map existing workflow steps to stable stage IDs**

Use `data-stage-id="collect"` for harvest, `data-stage-id="handoff"` for handoff, and `data-stage-id="write"` for writing.

- [ ] **Step 3: Preserve JavaScript hooks**

Do not rename IDs used by existing JavaScript: `queryForm`, `queryInput`, `analyzeBtn`, `cancelBtn`, `dropZone`, `fileInput`, `fileList`, `progressSection`, `logContainer`, `resultsSection`, `completionMessage`, `downloadBtn`, `progressFill`, `progressTrack`, `progressPctBadge`, `progressMsg`, `elapsedTimer`, and `progressPctText`.

### Task 3: Remove Remaining Graph and Figure UI Remnants

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Remove dead subgraph auto-switch JavaScript**

Delete the `loadDrugSubgraph` conditional block in the submit handler.

- [ ] **Step 2: Remove figure count from biomedical summary**

Delete `summary.figure_evidence` reads and the `Figures:` display line. Keep text evidence, clinical trials, and publications.

### Task 4: Add Small Status State Helper

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Add `setRunStatus(state, label, detail)`**

Update `runStatusBadge`, `runStatusText`, and `runStatusDetail` if present. Accept `idle`, `running`, `complete`, and `error`.

- [ ] **Step 2: Call helper from existing transitions**

Call it on page load, submit, completion, error, and cancel/reset. Keep existing progress and log behavior.

### Task 5: Verify and Merge

**Files:**
- Verify only.

- [ ] **Step 1: Run focused UI test**

Run: `pytest tests/test_investigation_ui.py -q --basetemp .pytest_tmp_investigation_ui_tdd`

Expected: PASS.

- [ ] **Step 2: Run focused backend/template regression**

Run: `pytest tests/test_report_narrative_api.py tests/test_pdf_extraction.py tests/test_chart_rendering.py tests/test_investigation_ui.py -q --basetemp .pytest_tmp_investigation_ui_final`

Expected: PASS or documented skips only.

- [ ] **Step 3: Compile modified Python**

Run: `python -m py_compile app.py config.py src\tools\pdf_processor.py src\tools\pubpeer_client.py src\tools\__init__.py src\engines\report_engine\utils\chart_injector.py src\agents\json_validator.py utils\retry_helper.py`

Expected: exit code 0.

- [ ] **Step 4: Commit branch and merge to main**

Run:

```powershell
git add app.py config.py docker-compose.yml requirements.txt src templates tests utils docs
git commit -m "feat: streamline investigation workflow ui"
git switch main
git merge --no-ff investigation-ui-workflow-optimization
```

Expected: merge succeeds and `main` contains the Investigation cleanup plus UI optimization.
