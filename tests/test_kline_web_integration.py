import os
import sys
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app import app
from src.kline.models import KlineWorkspacePayload
import src.kline.routes as kline_routes


def _install_fake_workspace_service(monkeypatch):
    class FakeWorkspaceService:
        def __init__(self):
            self.requested_symbols = []

        def build_workspace(self, symbol: str):
            self.requested_symbols.append(symbol)
            return KlineWorkspacePayload.example(symbol)

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


def test_backtest_run_api_returns_runner_payload(monkeypatch):
    def fake_run_kline_backtest(**kwargs):
        return {
            "run_id": "run-123",
            "ticker": kwargs["ticker"],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "metrics": {"sharpe": 1.2},
            "equity_curve": [{"date": kwargs["start_date"], "equity": 1.0}],
            "event_car": [],
        }

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fake_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "biib",
            "start_date": "2026-04-20",
            "end_date": "2026-04-21",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["run_id"] == "run-123"
    assert body["ticker"] == "BIIB"
    assert body["equity_curve"][0]["date"] == "2026-04-20"


def test_backtest_api_returns_signal_and_trade_overlays(monkeypatch):
    runner_payload = {
        "run_id": "run-with-overlays",
        "ticker": "BIIB",
        "start_date": "2026-04-20",
        "end_date": "2026-04-21",
        "metrics": {"sharpe": 1.2},
        "equity_curve": [{"date": "2026-04-20", "equity": 1.0}],
        "event_car": [],
        "signals": [
            {
                "date": "2026-04-20",
                "signal": 1,
                "signal_strength": 0.75,
                "source_event_ids": ["evt-1"],
            },
            {
                "date": "2026-04-21",
                "signal": 0,
                "signal_strength": 0.0,
                "source_event_ids": [],
            },
        ],
        "trades": [
            {
                "entry_date": "2026-04-21",
                "exit_date": "2026-04-21",
                "direction": "long",
                "size": 0.2,
                "entry_price": 101.0,
                "exit_price": 104.0,
                "pnl_pct": 0.029703,
            }
        ],
    }

    def fake_run_kline_backtest(**kwargs):
        return runner_payload

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fake_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "biib",
            "start_date": "2026-04-20",
            "end_date": "2026-04-21",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )

    assert response.status_code == 200
    assert response.get_json() == runner_payload


def test_backtest_run_api_rejects_invalid_ticker_without_runner(monkeypatch):
    def fail_run_kline_backtest(**kwargs):
        raise AssertionError("runner should not be called for invalid ticker")

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fail_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "../BIIB",
            "start_date": "2026-04-20",
            "end_date": "2026-04-21",
        },
    )
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"


def test_backtest_run_api_rejects_non_object_json_without_runner(monkeypatch):
    def fail_run_kline_backtest(**kwargs):
        raise AssertionError("runner should not be called for non-object JSON")

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fail_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        data="[1]",
        content_type="application/json",
    )
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "request body must be a JSON object"


def test_backtest_run_api_rejects_non_finite_risk_parameters(monkeypatch):
    def fail_run_kline_backtest(**kwargs):
        raise AssertionError("runner should not be called for invalid risk parameters")

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fail_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        data=(
            '{"ticker":"BIIB","start_date":"2026-04-20","end_date":"2026-04-21",'
            '"max_position_pct":NaN}'
        ),
        content_type="application/json",
    )
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "risk parameters must be finite numbers"


def test_backtest_run_api_rejects_out_of_range_risk_parameters(monkeypatch):
    def fail_run_kline_backtest(**kwargs):
        raise AssertionError("runner should not be called for invalid risk parameters")

    monkeypatch.setattr(kline_routes, "run_kline_backtest", fail_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "BIIB",
            "start_date": "2026-04-20",
            "end_date": "2026-04-21",
            "max_position_pct": 1.5,
        },
    )
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "max_position_pct must be greater than 0 and less than or equal to 1"


def test_backtest_result_api_returns_saved_payload(monkeypatch):
    def fake_load_saved_run(run_id: str):
        return {
            "run_id": run_id,
            "ticker": "BIIB",
            "metrics": {},
            "equity_curve": [],
            "event_car": [],
        }

    monkeypatch.setattr(kline_routes, "load_saved_run", fake_load_saved_run)

    client = app.test_client()
    response = client.get("/api/backtest/results/run-123")
    body = response.get_json()

    assert response.status_code == 200
    assert body["run_id"] == "run-123"
