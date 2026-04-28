import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import app as app_module
from app import app


def _fragment(*parts: str) -> str:
    return "".join(parts)


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
    assert "/static/vendor/pokie-chart.umd.js" in html
    assert "window.CassandraKline.renderChart" in html
    assert "kline-report-container" in html


def test_kline_template_uses_only_committed_chart_assets():
    template_path = os.path.join(PROJECT_ROOT, "templates", "kline_report.html")

    with open(template_path, encoding="utf-8") as template_file:
        template_source = template_file.read()

    assert _fragment("include ", '"', "partials") not in template_source
    assert _fragment("kline", "-", "chart", "-", "loader") not in template_source
    assert _fragment("kline", "_", "chart", "_", "loader") not in template_source
    assert _fragment("pokie", "-", "chart", "-", "loader") not in template_source
    assert "/static/vendor/pokie-chart.umd.js" in template_source
    assert "window.PokieChart.render" in template_source


def test_kline_template_uses_best_effort_local_storage_helpers():
    template_path = os.path.join(PROJECT_ROOT, "templates", "kline_report.html")

    with open(template_path, encoding="utf-8") as template_file:
        template_source = template_file.read()

    assert "function safeLocalStorageGet" in template_source
    assert "function safeLocalStorageSet" in template_source
    assert "safeLocalStorageGet('kline-last-run-' + ticker)" in template_source
    assert "safeLocalStorageSet('kline-last-run-' + ticker, pageState.lastRunId)" in template_source
    assert template_source.count("window.localStorage.getItem") == 1
    assert template_source.count("window.localStorage.setItem") == 1


def test_kline_template_guards_saved_run_hydration_from_newer_backtests():
    template_path = os.path.join(PROJECT_ROOT, "templates", "kline_report.html")

    with open(template_path, encoding="utf-8") as template_file:
        template_source = template_file.read()

    hydrate_function = template_source.split("async function hydrateBacktestRun(runId)", 1)[1]
    hydrate_function = hydrate_function.split("async function handleBacktestSubmit(event)", 1)[0]
    submit_function = template_source.split("async function handleBacktestSubmit(event)", 1)[1]
    submit_function = submit_function.split("function initializeBacktestDefaults()", 1)[0]

    assert "backtestRequestVersion: 0" in template_source
    assert "const hydrateVersion = pageState.backtestRequestVersion" in hydrate_function
    assert "hydrateVersion !== pageState.backtestRequestVersion" in hydrate_function
    assert "pageState.backtestRequestVersion += 1" in submit_function
    assert submit_function.find("pageState.backtestRequestVersion += 1") < submit_function.find("fetch('/api/backtest/run'")


def test_kline_template_scrolls_to_event_cards_without_raw_css_selector():
    template_path = os.path.join(PROJECT_ROOT, "templates", "kline_report.html")

    with open(template_path, encoding="utf-8") as template_file:
        template_source = template_file.read()

    scroll_function = template_source.split("function scrollToEventCard(eventId)", 1)[1]
    scroll_function = scroll_function.split("function populateFilterOptions()", 1)[0]

    assert "String(eventId)" in scroll_function
    assert "card.dataset.eventId === targetId" in scroll_function
    assert "querySelector('[data-event-id=\"" not in scroll_function


def test_kline_page_is_independent_from_report_analysis(monkeypatch):
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return [
            {
                "date": "2026-04-20",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 1200000,
            }
        ]

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return [
            {
                "id": "evt_001",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": ticker,
                "disease_area": "Alzheimer Disease",
                "catalyst": "Phase 3 readout",
                "sentiment": "positive",
                "source": "clinicaltrials",
            }
        ]

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert _fragment("/api/", "analyze") not in html
    assert _fragment("analysis", "_", "complete") not in html
    assert _fragment("request", "_", "report") not in html
    assert _fragment("data-tab=", '"', "report", '"') not in html
    assert _fragment("extract", "-", "signals-btn") not in html
    assert 'data-tab="events"' in html
    assert 'data-tab="backtest"' in html


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


def test_kline_template_has_visualization_and_backtest_tabs(monkeypatch):
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
    assert 'data-tab="backtest"' in html
    assert _fragment("data-tab=", '"', "report", '"') not in html
