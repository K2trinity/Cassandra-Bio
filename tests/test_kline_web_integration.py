import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app import app
from src.kline.models import KlineWorkspacePayload
import src.kline.routes as kline_routes


@pytest.fixture
def client():
    return app.test_client()


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


def test_kline_workspace_static_js_exposes_real_backtest_strategy_controls():
    workspace_js = (Path(PROJECT_ROOT) / "static" / "kline" / "workspace.js").read_text(
        encoding="utf-8",
    )

    for expected in [
        "/api/backtest/options",
        "strategy_id",
        "multifactor_score",
        "event_baseline",
        "price_source",
        "data_mode: \"real\"",
        "data_snapshot_id",
    ]:
        assert expected in workspace_js
    assert "mock_multifactor_demo" not in workspace_js


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


def test_backtest_options_api_returns_real_strategy_and_snapshot_options(monkeypatch):
    monkeypatch.setattr(
        kline_routes,
        "_list_recent_data_snapshots",
        lambda limit=10: [
            {
                "data_snapshot_id": "snap_20260509_df843b255a1e",
                "snapshot_date": "2026-05-09",
                "price_source": "tiingo",
                "universe_id": "biotech_us_v1",
                "bias_profile": "current_constituents_only",
                "created_at": "2026-05-09 10:36:50",
            }
        ],
        raising=False,
    )

    client = app.test_client()
    response = client.get("/api/backtest/options")
    body = response.get_json()

    assert response.status_code == 200
    assert body["default_strategy_id"] == "multifactor_score"
    assert [item["id"] for item in body["strategies"]] == [
        "multifactor_score",
        "event_baseline",
    ]
    assert body["default_price_source"] == "tiingo"
    assert body["default_data_snapshot_id"] == "snap_20260509_df843b255a1e"
    assert body["snapshots"][0]["snapshot_date"] == "2026-05-09"


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


def test_backtest_api_defaults_to_real_multifactor_without_template_mock_disclosure(
    monkeypatch, tmp_path
):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-02") + pd.offsets.BDay(index),
                "open": 100.0 + index,
                "high": 103.0 + index,
                "low": 99.0 + index,
                "close": 102.0 + index if index % 4 in {1, 2} else 100.5 + index,
                "volume": 1_000_000 + index * 20_000,
            }
            for index in range(45)
        ]
    )

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(
        runner,
        "build_mock_ohlc_frame",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("default API backtest must not use mock OHLC")
        ),
    )
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])
    monkeypatch.setattr(
        runner, "compute_event_car", lambda price_window, event_rows: pd.DataFrame()
    )
    _install_fake_workspace_service(monkeypatch)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["mock_metadata"] is None
    assert body["strategy"]["id"] == "multifactor_score"
    assert body["strategy"]["data_mode"] == "real"
    assert body["strategy"]["price_basis"] == "visible_ohlc"
    assert body["exposure_summary"]["exposure_days"] >= len(body["trades"])

    html = client.get("/kline/MRNA").get_data(as_text=True).lower()
    assert "mock" not in html
    assert "synthetic" not in html


def test_backtest_api_rejects_explicit_mock_strategy_for_non_a_ticker(
    monkeypatch, tmp_path
):
    from src.backtest import runner

    def fail_load_ohlc(ticker):
        raise AssertionError("strategy access should be validated before OHLC load")

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", fail_load_ohlc)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "PFE",
            "start_date": "2025-01-02",
            "end_date": "2025-01-08",
            "strategy_id": "mock_multifactor_demo",
            "data_mode": "mock",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )

    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "mock_multifactor_demo requires mock_scope='biotech_mock_v1'"
    )


def test_backtest_api_rejects_mock_strategy_in_real_mode():
    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-01-08",
            "strategy_id": "mock_multifactor_demo",
            "data_mode": "real",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "mock_multifactor_demo requires data_mode='mock'"
    }


def test_backtest_portfolio_run_api_returns_real_runner_payload(monkeypatch):
    captured_kwargs = {}

    def fake_run_real_biotech_portfolio_backtest(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "run_id": "portfolio-123",
            "created_at": "2026-05-06T12:00:00",
            "universe_id": kwargs["universe_id"],
            "tickers": ["BIIB", "MRNA", "VRTX"],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "strategy": {"id": "multifactor_score"},
            "portfolio_equity_curve": [
                {"date": kwargs["start_date"], "equity": 1.0},
            ],
            "portfolio_metrics": {
                "strategy_return": 0.04,
                "best_ticker": "VRTX",
                "worst_ticker": "MRNA",
                "total_trades": 8,
                "avg_active_signal_days": 6.5,
            },
            "constituents": [
                {
                    "ticker": "MRNA",
                    "strategy_return": 0.02,
                    "active_signal_days": 6,
                    "trade_count": 2,
                    "metrics": {"sharpe": 1.1},
                    "baseline": {"strategy_return": 0.02},
                    "factor_attribution": {"active_factor_days": 6},
                }
            ],
            "focus_ticker": {
                "ticker": kwargs["focus_ticker"],
                "equity_curve": [{"date": kwargs["start_date"], "equity": 1.0}],
                "signals": [],
                "trades": [],
                "metrics": {},
                "baseline": {},
                "factor_attribution": {},
            },
        }

    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        fake_run_real_biotech_portfolio_backtest,
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "lly",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "stop_loss_pct": -0.07,
            "max_position_pct": 0.15,
            "slippage_pct": 0.002,
            "holding_period_days": 7,
            "universe_id": "biotech_custom_v2",
            "strategy_id": "event_baseline",
            "price_source": "tiingo",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert captured_kwargs == {
        "focus_ticker": "LLY",
        "start_date": "2025-01-02",
        "end_date": "2025-03-31",
        "stop_loss_pct": -0.07,
        "max_position_pct": 0.15,
        "slippage_pct": 0.002,
        "holding_period_days": 7,
        "universe_id": "biotech_custom_v2",
        "strategy_id": "event_baseline",
        "as_of_date": None,
        "data_snapshot_id": "snap_20260507_tiingo",
        "price_source": "tiingo",
    }
    assert body["run_id"] == "portfolio-123"
    assert body["universe_id"] == "biotech_custom_v2"
    assert body["strategy"] == {"id": "multifactor_score"}
    assert body["focus_ticker"]["ticker"] == "LLY"
    assert body["portfolio_metrics"]["strategy_return"] == 0.04
    assert body["constituents"][0]["strategy_return"] == 0.02
    body_text = json.dumps(body, sort_keys=True).lower()
    for forbidden in ["mock", "synthetic", "data_mode", "positive_demo_expected"]:
        assert forbidden not in body_text


def test_backtest_portfolio_run_api_requires_data_snapshot(monkeypatch):
    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("route must reject before invoking portfolio runner")
        ),
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "lly",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "price_source": "tiingo",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "data_snapshot_id is required for portfolio backtests"
    }


def test_backtest_portfolio_run_api_rejects_visible_cache_price_source(monkeypatch):
    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("route must reject before invoking portfolio runner")
        ),
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "lly",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "price_source": "yfinance",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "portfolio backtests require tiingo snapshot prices"
    }


def test_demo_portfolio_endpoint_is_not_available(client):
    removed_demo_endpoint = "/api/backtest/portfolio/" + "demo/run"
    response = client.post(
        removed_demo_endpoint,
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "price_source": "tiingo",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )

    assert response.status_code == 404


def test_backtest_run_api_rejects_invalid_holding_period():
    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "holding_period_days": 0,
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "holding_period_days must be an integer between 1 and 60"
    }


def test_backtest_portfolio_run_api_reuses_single_run_validation(monkeypatch):
    def fail_run_real_biotech_portfolio_backtest(**kwargs):
        raise AssertionError("portfolio runner should not be called")

    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        fail_run_real_biotech_portfolio_backtest,
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "../LLY",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
        },
    )

    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"
    )


def test_backtest_portfolio_run_api_returns_400_on_runner_error(monkeypatch):
    def fake_run_real_biotech_portfolio_backtest(**kwargs):
        return {
            "error": "LLY: no real OHLC data",
            "universe_id": kwargs["universe_id"],
            "as_of_date": kwargs["as_of_date"],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "data_credibility": {
                "eligible_universe_count": 3,
                "skipped_ticker_count": 0,
                "survivorship_bias_warning": True,
                "universe_bias_status": "current_constituents_only",
            },
        }

    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        fake_run_real_biotech_portfolio_backtest,
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "price_source": "tiingo",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "LLY: no real OHLC data",
        "universe_id": "biotech_us_v1",
        "as_of_date": None,
        "start_date": "2025-01-02",
        "end_date": "2025-03-31",
        "data_credibility": {
            "eligible_universe_count": 3,
            "skipped_ticker_count": 0,
            "survivorship_bias_warning": True,
            "universe_bias_status": "current_constituents_only",
        },
    }


def test_backtest_portfolio_run_api_returns_400_for_unsupported_universe():
    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "universe_id": "biotech_mock_v1",
            "price_source": "tiingo",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Unsupported production universe: biotech_mock_v1",
        "universe_id": "biotech_mock_v1",
        "data_snapshot_id": "snap_20260507_tiingo",
        "as_of_date": "2025-03-31",
        "start_date": "2025-01-02",
        "end_date": "2025-03-31",
        "data_credibility": {
            "eligible_universe_count": 0,
            "skipped_ticker_count": 0,
            "survivorship_bias_warning": True,
            "universe_bias_status": "current_constituents_only",
            "coverage_status": "unsupported_universe",
        },
    }


def test_backtest_portfolio_run_api_allows_syntactically_valid_focus_ticker(
    monkeypatch,
):
    captured_kwargs = {}

    def fake_run_real_biotech_portfolio_backtest(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "run_id": "portfolio-pfe",
            "universe_id": kwargs["universe_id"],
            "focus_ticker": {"ticker": "BIIB"},
            "portfolio_metrics": {},
            "constituents": [],
        }

    monkeypatch.setattr(
        kline_routes,
        "run_real_biotech_portfolio_backtest",
        fake_run_real_biotech_portfolio_backtest,
        raising=False,
    )

    client = app.test_client()
    response = client.post(
        "/api/backtest/portfolio/run",
        json={
            "ticker": "PFE",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "price_source": "tiingo",
            "data_snapshot_id": "snap_20260507_tiingo",
        },
    )

    assert response.status_code == 200
    assert captured_kwargs["focus_ticker"] == "PFE"
    assert captured_kwargs["universe_id"] == "biotech_us_v1"
    assert captured_kwargs["as_of_date"] is None
    assert captured_kwargs["data_snapshot_id"] == "snap_20260507_tiingo"
    assert captured_kwargs["price_source"] == "tiingo"
