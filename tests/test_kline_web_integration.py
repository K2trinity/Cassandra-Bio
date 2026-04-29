import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app import app
from src.kline.models import KlineWorkspacePayload
import src.kline.routes as kline_routes


def _legacy_literal(*parts):
    return "".join(parts)


LEGACY_KLINE_TEMPLATE_REFERENCES = (
    _legacy_literal("kline", ".html"),
    _legacy_literal("kline_", "report.html"),
    _legacy_literal("kline_chart_", "runtime.html"),
    _legacy_literal("kline_chart_", "assets.html"),
)

LEGACY_KLINE_ANALYSIS_ENDPOINT = _legacy_literal("/api/", "analyze")

LEGACY_KLINE_BRIDGE_REFERENCES = (
    _legacy_literal("request", "_report"),
    _legacy_literal("analysis", "_complete"),
)


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
    assert 'data-ticker="MRNA"' in html
    assert 'id="kline-workspace-data" type="application/json"' in html
    assert 'data-role="ticker-selector"' in html
    assert 'id="source-strip"' in html
    assert 'id="company-name"' in html
    assert 'id="last-close"' in html
    assert 'id="coverage-range"' in html
    assert 'id="hover-readout"' in html
    assert 'id="layer-bar"' in html
    assert 'id="kline-container"' in html
    assert 'id="range-context"' in html
    assert 'data-panel="catalysts"' in html
    assert 'data-panel="details"' in html
    assert 'data-panel="backtest"' in html
    assert 'data-panel="status"' in html
    assert "/static/kline/workspace.css" in html
    assert "/static/vendor/pokie-chart.umd.js" in html
    assert "/static/kline/workspace.js" in html
    assert LEGACY_KLINE_ANALYSIS_ENDPOINT not in html
    for reference in LEGACY_KLINE_BRIDGE_REFERENCES:
        assert reference not in html


def test_kline_workspace_renders_disabled_future_capability_contracts(monkeypatch):
    _install_fake_workspace_service(monkeypatch)
    client = app.test_client()

    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '"id": "news"' in html
    assert '"enabled": false' in html
    assert '"phase": 2' in html
    assert '"id": "range_analysis"' in html
    assert '"phase": 3' in html


def test_kline_workspace_invalid_ticker_has_recovery_link(monkeypatch):
    class FailingWorkspaceService:
        def build_workspace(self, symbol: str):
            raise ValueError(
                "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"
            )

    monkeypatch.setattr(kline_routes, "workspace_service", FailingWorkspaceService())
    client = app.test_client()

    response = client.get("/kline/BAD!")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Invalid ticker" in html
    assert "invalid ticker: use 1-16 letters, numbers, dots, or hyphens" in html
    assert 'href="/kline"' in html
    assert 'id="kline-workspace-data"' not in html


def test_kline_default_rejects_path_like_query_symbol():
    client = app.test_client()

    response = client.get("/kline?symbol=../MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Invalid ticker" in html
    assert "invalid ticker: use 1-16 letters, numbers, dots, or hyphens" in html


def test_kline_path_like_symbol_uses_invalid_ticker_page():
    client = app.test_client()

    response = client.get("/kline/..%2FMRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Invalid ticker" in html
    assert "invalid ticker: use 1-16 letters, numbers, dots, or hyphens" in html


def test_kline_workspace_static_js_uses_phase1_contracts_only():
    workspace_js = (Path(PROJECT_ROOT) / "static" / "kline" / "workspace.js").read_text(
        encoding="utf-8",
    )

    assert "/api/backtest/run" in workspace_js
    assert "/api/kline/range-context/" in workspace_js
    assert "PokieChart.render" in workspace_js
    assert LEGACY_KLINE_ANALYSIS_ENDPOINT not in workspace_js
    for reference in LEGACY_KLINE_BRIDGE_REFERENCES:
        assert reference not in workspace_js
    assert "Socket.IO" not in workspace_js


def test_kline_workspace_template_omits_legacy_report_bridge_references():
    template_source = (
        Path(PROJECT_ROOT) / "templates" / "kline_workspace.html"
    ).read_text(encoding="utf-8")

    for reference in LEGACY_KLINE_TEMPLATE_REFERENCES:
        assert reference not in template_source
    assert LEGACY_KLINE_ANALYSIS_ENDPOINT not in template_source
    for reference in LEGACY_KLINE_BRIDGE_REFERENCES:
        assert reference not in template_source


def test_kline_workspace_api_returns_workspace_json(monkeypatch):
    fake_service = _install_fake_workspace_service(monkeypatch)
    client = app.test_client()

    response = client.get("/api/kline/workspace/MRNA")
    body = response.get_json()

    assert response.status_code == 200
    assert fake_service.requested_symbols == ["MRNA"]
    assert body["ticker"] == "MRNA"


def test_kline_events_api_returns_all_phase2_event_layers(monkeypatch):
    from src.kline.models import (
        KlineCompany,
        KlineEvent,
        KlineLayer,
        KlinePanelState,
        KlinePriceSeries,
    )

    clinical = KlineEvent.example("MRNA")
    clinical.id = "clinical-1"
    news = KlineEvent(
        id="news-1",
        ticker="MRNA",
        date="2026-04-21",
        type="market_news",
        category="news",
        title="Market news",
        summary="Market news",
        sentiment="positive",
        priority=3,
        confidence="medium",
        source="alphavantage",
    )
    macro = KlineEvent(
        id="macro-1",
        ticker="MRNA",
        date="2026-04-22",
        type="macro_economic",
        category="macro",
        title="Macro event",
        summary="Macro event",
        sentiment="neutral",
        priority=3,
        confidence="low",
        source="gdelt",
    )

    class FakeWorkspaceService:
        def build_workspace(self, symbol: str):
            return KlineWorkspacePayload(
                ticker="MRNA",
                company=KlineCompany.example("MRNA"),
                price=KlinePriceSeries.empty(),
                layers=[
                    KlineLayer(
                        id="candles",
                        kind="candles",
                        label="Candles",
                        visible_by_default=True,
                        status="empty",
                    ),
                    KlineLayer(
                        id="catalysts",
                        kind="catalysts",
                        label="Catalysts",
                        visible_by_default=True,
                        status="ready",
                        points=[clinical],
                    ),
                    KlineLayer(
                        id="news",
                        kind="news",
                        label="News",
                        visible_by_default=True,
                        status="ready",
                        points=[news],
                    ),
                    KlineLayer(
                        id="macro",
                        kind="macro",
                        label="Macro",
                        visible_by_default=False,
                        status="ready",
                        points=[macro],
                    ),
                ],
                panels=KlinePanelState(),
                data_status=[],
                warnings=[],
                capabilities=[],
            )

    monkeypatch.setattr(kline_routes, "workspace_service", FakeWorkspaceService())
    client = app.test_client()

    response = client.get("/api/kline/events/MRNA")
    body = response.get_json()

    assert response.status_code == 200
    assert [event["id"] for event in body] == ["clinical-1", "news-1", "macro-1"]


def test_obsolete_kline_surface_files_are_removed():
    obsolete_paths = (
        Path(PROJECT_ROOT) / "templates" / _legacy_literal("kline", ".html"),
        Path(PROJECT_ROOT) / "templates" / _legacy_literal("kline_", "report.html"),
        Path(PROJECT_ROOT)
        / "templates"
        / "partials"
        / _legacy_literal("kline_chart_", "assets.html"),
        Path(PROJECT_ROOT)
        / "templates"
        / "partials"
        / _legacy_literal("kline_chart_", "runtime.html"),
        Path(PROJECT_ROOT)
        / "static"
        / "vendor"
        / _legacy_literal("pokie-", "chart-loader.js"),
    )

    for obsolete_path in obsolete_paths:
        assert not obsolete_path.exists(), f"{obsolete_path} should be removed"


def test_kline_template_cleanup_references_are_absent():
    templates_dir = Path(PROJECT_ROOT) / "templates"

    for template_path in templates_dir.rglob("*.html"):
        template_source = template_path.read_text(encoding="utf-8")
        for reference in LEGACY_KLINE_TEMPLATE_REFERENCES:
            assert (
                reference not in template_source
            ), f"{reference} referenced by {template_path}"


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
    assert (
        body["error"] == "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"
    )


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
    assert (
        body["error"]
        == "max_position_pct must be greater than 0 and less than or equal to 1"
    )


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
