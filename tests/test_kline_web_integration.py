import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import app as app_module
from app import app


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


def test_kline_page_renders_chart_assets_from_head_block():
    client = app.test_client()

    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "/static/vendor/pokie-chart.css" in html
    assert "kline-report-container" in html


def test_kline_page_uses_main_analysis_event_flow():
    client = app.test_client()

    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "/api/analyze" in html
    assert "analysis_complete" in html
    assert "report_ready" not in html


def test_request_report_bridges_into_main_analysis_queue(monkeypatch):
    def fake_analyze():
        return app_module.jsonify({
            "status": "accepted",
            "message": "Analysis started. Monitor progress via WebSocket.",
            "query": "stub",
            "task_id": "task-123",
        }), 202

    monkeypatch.setattr(app_module, "analyze", fake_analyze)

    client = app_module.socketio.test_client(app_module.app)
    client.emit("request_report", {
        "ticker": "MRNA",
        "event_id": "evt_001",
        "event_type": "clinical_readout",
        "date": "2026-04-20",
        "catalyst": "Phase 3 trial positive results",
    })
    received = client.get_received()

    assert any(
        packet["name"] == "report_queued" and packet["args"][0]["task_id"] == "task-123"
        for packet in received
    )


def test_kline_route_uses_real_data_service_for_ohlc(monkeypatch):
    """
    Contract: /kline/<symbol> must call get_ohlc_rows(ticker: str, max_age_hours: int = 24) -> list[dict]
    and use the returned OHLC rows instead of inline mock-loop data generation.
    """
    mock_ohlc_rows = [
        {
            "date": "2026-04-19",
            "open": 100.0,
            "high": 102.5,
            "low": 99.0,
            "close": 101.5,
            "volume": 1000000,
        },
        {
            "date": "2026-04-20",
            "open": 101.5,
            "high": 103.0,
            "low": 101.0,
            "close": 102.0,
            "volume": 1100000,
        },
    ]

    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return mock_ohlc_rows

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "101.5" in html  # Verify service-returned data is in the response
    assert "102.0" in html


def test_kline_route_uses_real_data_service_for_events(monkeypatch):
    """
    Contract: /kline/<symbol> must call get_events_for_ticker(ticker: str, max_age_hours: int = 6) -> list[dict]
    and use the returned events instead of inline mock data.
    """
    mock_ohlc_rows = [
        {
            "date": "2026-04-19",
            "open": 100.0,
            "high": 102.5,
            "low": 99.0,
            "close": 101.5,
            "volume": 1000000,
        },
    ]

    mock_events = [
        {
            "id": "evt_real_001",
            "date": "2026-04-15",
            "type": "clinical_readout",
            "catalyst": "Real Phase 3 data from service",
        },
    ]

    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return mock_ohlc_rows

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return mock_events

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Real Phase 3 data from service" in html


def test_kline_route_handles_empty_ohlc_and_events(monkeypatch):
    """
    Contract: /kline/<symbol> must render successfully even when services return empty lists.
    Template receives ohlc_json=[] and events_json=[].
    """
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return []

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return []

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "[]" in html  # Empty JSON arrays should be in the response


def test_kline_template_has_three_tab_shell(monkeypatch):
    """
    Contract: kline_report.html must have a three-tab shell with:
    - data-tab="events"
    - data-tab="report"
    - data-tab="backtest"
    """
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return []

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return []

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-tab="events"' in html
    assert 'data-tab="report"' in html
    assert 'data-tab="backtest"' in html
