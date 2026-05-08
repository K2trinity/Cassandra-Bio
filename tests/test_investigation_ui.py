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
