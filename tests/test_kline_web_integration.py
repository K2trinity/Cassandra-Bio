import os
import sys
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app import app


def _install_fake_workspace_service(monkeypatch):
    import src.kline.routes as kline_routes

    payload_cls = kline_routes.KlineWorkspacePayload

    class FakeWorkspaceService:
        def __init__(self):
            self.requested_symbols = []

        def build_workspace(self, symbol: str):
            self.requested_symbols.append(symbol)
            return payload_cls.example(symbol)

    fake_service = FakeWorkspaceService()
    monkeypatch.setattr(kline_routes, "workspace_service", fake_service)
    return fake_service


def test_root_redirects_to_new_investigation():
    client = app.test_client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code in (301, 302)
    assert response.headers["Location"].endswith("/investigation")


def test_investigation_page_renders_head_assets_from_base_template():
    client = app.test_client()

    response = client.get("/investigation")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "marked.min.js" in html
    assert ".prose h1" in html
    assert 'href="/kline"' in html


def test_kline_page_renders_phase1_workspace(monkeypatch):
    fake_service = _install_fake_workspace_service(monkeypatch)
    client = app.test_client()

    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert fake_service.requested_symbols == ["MRNA"]
    assert 'id="kline-workspace"' in html
    assert 'data-role="ticker-selector"' in html
    assert 'data-panel="catalysts"' in html
    assert 'data-panel="details"' in html
    assert 'data-panel="backtest"' in html
    assert 'data-panel="status"' in html
    assert "/static/vendor/pokie-chart.umd.js" in html
    assert "/static/kline/workspace.js" in html
    assert "/api/analyze" not in html
    assert "request_report" not in html


def test_kline_workspace_api_returns_workspace_json(monkeypatch):
    fake_service = _install_fake_workspace_service(monkeypatch)
    client = app.test_client()

    response = client.get("/api/kline/workspace/MRNA")
    body = response.get_json()

    assert response.status_code == 200
    assert fake_service.requested_symbols == ["MRNA"]
    assert body["ticker"] == "MRNA"


def test_kline_template_cleanup_references_are_absent():
    stale_references = {
        "kline_report.html",
        "kline_chart_runtime.html",
        "kline_chart_assets.html",
    }
    templates_dir = Path(PROJECT_ROOT) / "templates"

    for template_path in templates_dir.rglob("*.html"):
        template_source = template_path.read_text(encoding="utf-8")
        for reference in stale_references:
            assert reference not in template_source, f"{reference} referenced by {template_path}"
