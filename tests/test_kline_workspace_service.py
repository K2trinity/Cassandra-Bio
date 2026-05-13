import json
from types import SimpleNamespace


def _contracts():
    from src.kline.models import KlineDataStatus, KlineEvent, KlinePriceSeries
    from src.kline.providers.catalyst_provider import CatalystEventProvider
    from src.kline.providers.ohlc_provider import OHLCProvider
    from src.kline.ticker_resolver import TickerResolver
    from src.kline.workspace_service import KlineWorkspaceService

    return SimpleNamespace(
        CatalystEventProvider=CatalystEventProvider,
        KlineDataStatus=KlineDataStatus,
        KlineEvent=KlineEvent,
        KlinePriceSeries=KlinePriceSeries,
        KlineWorkspaceService=KlineWorkspaceService,
        OHLCProvider=OHLCProvider,
        TickerResolver=TickerResolver,
    )


class FakeOHLCProvider:
    def __init__(self, KlineDataStatus, KlinePriceSeries):
        self.KlineDataStatus = KlineDataStatus
        self.KlinePriceSeries = KlinePriceSeries
        self.requests = []

    def load(self, ticker: str, cache_only: bool = False):
        self.requests.append((ticker, cache_only))
        return (
            self.KlinePriceSeries(
                rows=[
                    {
                        "date": "2026-04-20",
                        "open": 101.0,
                        "high": 104.0,
                        "low": 100.0,
                        "close": 103.0,
                        "volume": 1200000,
                    }
                ],
                date_range={"start": "2026-04-20", "end": "2026-04-20"},
                last_close=103.0,
                cache_status="ready",
                last_updated=None,
            ),
            [self.KlineDataStatus(source="ohlc", status="ready", item_count=1)],
        )


class FakeCatalystProvider:
    def __init__(self, KlineDataStatus, KlineEvent):
        self.KlineDataStatus = KlineDataStatus
        self.KlineEvent = KlineEvent
        self.requests = []

    def load(self, ticker: str, cache_only: bool = False):
        self.requests.append((ticker, cache_only))
        return (
            [
                self.KlineEvent(
                    id="evt-1",
                    ticker=ticker,
                    date="2026-04-20",
                    type="clinical_readout",
                    category="clinical",
                    title="Phase 3 readout",
                    summary="Phase 3 readout",
                    sentiment="positive",
                    priority=1,
                    confidence="high",
                    source="clinicaltrials",
                    source_url="https://clinicaltrials.gov/study/NCT00000001",
                    source_ids=["NCT00000001"],
                    source_entity="ModernaTX, Inc.",
                    disease_area="Melanoma",
                    drug_name=None,
                    impact_score=None,
                    metadata={},
                )
            ],
            [
                self.KlineDataStatus(
                    source="clinicaltrials",
                    status="ready",
                    item_count=1,
                )
            ],
        )


class FakeBacktestProvider:
    def __init__(self):
        self.requests = []

    def load_last_run(self, ticker: str):
        self.requests.append(ticker)
        return None


def _service(contracts):
    return contracts.KlineWorkspaceService(
        resolver=contracts.TickerResolver(),
        ohlc_provider=FakeOHLCProvider(
            contracts.KlineDataStatus,
            contracts.KlinePriceSeries,
        ),
        catalyst_provider=FakeCatalystProvider(
            contracts.KlineDataStatus,
            contracts.KlineEvent,
        ),
        backtest_provider=FakeBacktestProvider(),
    )


def test_ticker_resolver_normalizes_known_symbol():
    contracts = _contracts()
    resolver = contracts.TickerResolver()

    company = resolver.resolve(" mrna ")

    assert company.ticker == "MRNA"
    assert company.name == "Moderna, Inc."
    assert company.is_biotech is True


def test_ticker_resolver_maps_vertex_company_text_to_vrtx():
    contracts = _contracts()
    resolver = contracts.TickerResolver()

    assert resolver.resolve("vertex").ticker == "VRTX"
    assert resolver.resolve("Vertex Pharmaceuticals").ticker == "VRTX"


def test_ticker_resolver_rejects_path_like_symbols():
    contracts = _contracts()
    resolver = contracts.TickerResolver()

    assert resolver.normalize("../MRNA") is None


def test_ticker_resolver_returns_copies_for_known_symbols():
    contracts = _contracts()
    resolver = contracts.TickerResolver()

    company = resolver.resolve("MRNA")
    company.aliases.append("mutated alias")

    assert "mutated alias" not in resolver.resolve("MRNA").aliases
    assert "mutated alias" not in [
        alias
        for universe_company in resolver.list_universe()
        if universe_company.ticker == "MRNA"
        for alias in universe_company.aliases
    ]


def test_ticker_resolver_reads_latest_research_universe_snapshot(tmp_path):
    from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot
    from src.backtest.universe_catalog import write_universe_snapshot

    contracts = _contracts()
    db_path = tmp_path / "cassandra_research.duckdb"
    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="RARE",
                company_name="Ultragenyx Pharmaceutical Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="nasdaq_trader_keyword",
                industry="Biotechnology",
            ),
            UniverseSourceRow(
                ticker="XBI",
                company_name="SPDR S&P Biotech ETF",
                exchange="NYSEARCA",
                asset_type="etf",
                source="xbi",
            ),
        ],
        as_of_date="2026-05-13",
    )
    write_universe_snapshot(snapshot, db_path=db_path)

    resolver = contracts.TickerResolver(db_path=db_path)

    assert [company.ticker for company in resolver.list_universe()] == ["RARE"]
    resolved = resolver.resolve("rare")
    assert resolved.ticker == "RARE"
    assert resolved.name == "Ultragenyx Pharmaceutical Inc."
    assert resolved.is_biotech is True


def test_ohlc_provider_returns_error_status_for_malformed_rows():
    contracts = _contracts()
    provider = contracts.OHLCProvider(
        fetch_rows=lambda ticker, max_age_hours=24: ["bad-row"]
    )

    price, statuses = provider.load("MRNA")

    assert price.rows == []
    assert price.cache_status == "error"
    assert statuses[0].source == "ohlc"
    assert statuses[0].status == "error"
    assert statuses[0].item_count == 0
    assert statuses[0].message


def test_ohlc_provider_preserves_status_payload_metadata():
    contracts = _contracts()
    provider = contracts.OHLCProvider(
        fetch_rows=lambda ticker, max_age_hours=24: {
            "rows": [
                {
                    "date": "2026-04-20",
                    "open": 101.0,
                    "high": 104.0,
                    "low": 100.0,
                    "close": 103.0,
                    "volume": 1200000,
                }
            ],
            "status": "stale",
            "message": "using stale cache after refresh failed",
        }
    )

    price, statuses = provider.load("MRNA")

    assert price.rows[0]["date"] == "2026-04-20"
    assert price.cache_status == "stale"
    assert statuses[0].source == "ohlc"
    assert statuses[0].status == "stale"
    assert statuses[0].item_count == 1
    assert statuses[0].message == "using stale cache after refresh failed"


def test_catalyst_provider_preserves_requested_ticker():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "raw-1",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": "ModernaTX,",
                "disease_area": "Melanoma",
                "catalyst": "Phase 3 readout",
                "sentiment": "positive",
                "source": "clinicaltrials",
                "source_entity": "ModernaTX, Inc.",
                "source_ids": ["NCT00000001"],
            }
        ],
        fetch_statuses=None,
    )

    events, statuses = provider.load("MRNA")

    assert events[0].ticker == "MRNA"
    assert events[0].source_entity == "ModernaTX, Inc."
    assert events[0].source_ids == ["NCT00000001"]
    assert statuses[0].source == "clinicaltrials"
    assert statuses[0].status == "ready"


def test_catalyst_provider_uses_raw_impact_when_score_fields_are_missing():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "raw-impact-1",
                "date": "2026-04-21",
                "type": "clinical_readout",
                "ticker": "MRNA",
                "catalyst": "Durable response update",
                "sentiment": "positive",
                "source": "clinicaltrials",
                "impact": "high",
                "metadata": {"note": "keep"},
            }
        ],
        fetch_statuses=None,
    )

    events, _statuses = provider.load("MRNA")

    assert events[0].impact_score == "high"
    assert events[0].metadata["impact"] == "high"
    assert events[0].metadata["note"] == "keep"


def test_catalyst_provider_projects_phase2_metadata_fields():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "news-1",
                "date": "2026-04-21",
                "type": "market_news",
                "ticker": "MRNA",
                "category": "clinical",
                "title": "Market news",
                "summary": "Market news",
                "sentiment": "positive",
                "source": "alphavantage",
                "metadata": {
                    "category": "news",
                    "source_tier": "market_news",
                    "source_kind": "market_news",
                    "confidence_score": 0.76,
                    "impact_score": 0.55,
                    "backtest_eligible": True,
                },
            }
        ],
        fetch_statuses=None,
    )

    events, _statuses = provider.load("MRNA")

    assert events[0].category == "news"
    assert events[0].source_tier == "market_news"
    assert events[0].source_kind == "market_news"
    assert events[0].confidence_score == 0.76
    assert events[0].impact_score == 0.55
    assert events[0].backtest_eligible is True


def test_catalyst_provider_uses_injected_status_rows():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "raw-1",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "ticker": "MRNA",
                "catalyst": "Phase 3 readout",
                "source": "clinicaltrials",
            }
        ],
        fetch_statuses=lambda ticker: [
            {
                "source": "openfda",
                "item_count": 0,
                "last_fetch_at": "2026-04-20T10:00:00",
            },
            {
                "source": "clinicaltrials",
                "item_count": 3,
                "last_fetch_at": "2026-04-20T10:05:00",
            },
        ],
    )

    _events, statuses = provider.load("MRNA")

    assert [status.to_dict() for status in statuses] == [
        {
            "source": "openfda",
            "status": "empty",
            "item_count": 0,
            "last_fetch_at": "2026-04-20T10:00:00",
            "message": None,
        },
        {
            "source": "clinicaltrials",
            "status": "ready",
            "item_count": 3,
            "last_fetch_at": "2026-04-20T10:05:00",
            "message": None,
        },
    ]


def test_catalyst_provider_preserves_error_status_rows():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [],
        fetch_statuses=lambda ticker: [
            {
                "source": "openfda",
                "status": "rate_limited",
                "item_count": 0,
                "last_fetch_at": "2026-04-20T10:00:00",
                "message": "429 Too Many Requests",
            }
        ],
    )

    _events, statuses = provider.load("MRNA")

    assert [status.to_dict() for status in statuses] == [
        {
            "source": "openfda",
            "status": "rate_limited",
            "item_count": 0,
            "last_fetch_at": "2026-04-20T10:00:00",
            "message": "429 Too Many Requests",
        }
    ]


def test_catalyst_provider_classifies_report_events():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "report-1",
                "date": "2026-04-20",
                "ticker": "MRNA",
                "type": "cassandra_report",
                "category": "report",
                "title": "Cassandra thesis update",
                "source": "report",
            }
        ],
        fetch_statuses=None,
    )

    events, _statuses = provider.load("MRNA")

    assert events[0].category == "report"


def test_catalyst_provider_keeps_reported_clinical_results_clinical():
    contracts = _contracts()
    provider = contracts.CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "clinical-1",
                "date": "2026-04-20",
                "ticker": "MRNA",
                "type": "clinical_readout",
                "category": "clinical",
                "title": "Reported Phase 3 results met primary endpoint",
                "source": "clinicaltrials",
            }
        ],
        fetch_statuses=None,
    )

    events, _statuses = provider.load("MRNA")

    assert events[0].category == "clinical"


def test_catalyst_provider_default_fetch_statuses_uses_fetch_log_helper(monkeypatch):
    contracts = _contracts()
    from src.services import event_ingestion_service

    calls = []

    def fake_events(ticker, max_age_hours=6):
        return [
            {
                "id": "raw-1",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "ticker": ticker,
                "catalyst": "Phase 3 readout",
                "source": "clinicaltrials",
            }
        ]

    def fake_statuses(ticker):
        calls.append(ticker)
        return [
            {
                "source": "openfda",
                "item_count": 0,
                "last_fetch_at": "2026-04-20T10:00:00",
            },
            {
                "source": "clinicaltrials",
                "item_count": 1,
                "last_fetch_at": "2026-04-20T10:05:00",
            },
        ]

    monkeypatch.setattr(
        event_ingestion_service,
        "get_source_statuses_for_ticker",
        fake_statuses,
    )
    provider = contracts.CatalystEventProvider(fetch_events=fake_events)

    _events, statuses = provider.load(" mrna ")

    assert calls == ["MRNA"]
    assert [status.to_dict() for status in statuses] == [
        {
            "source": "openfda",
            "status": "empty",
            "item_count": 0,
            "last_fetch_at": "2026-04-20T10:00:00",
            "message": None,
        },
        {
            "source": "clinicaltrials",
            "status": "ready",
            "item_count": 1,
            "last_fetch_at": "2026-04-20T10:05:00",
            "message": None,
        },
    ]


def test_workspace_warnings_include_failed_source_statuses():
    contracts = _contracts()

    class RateLimitedCatalystProvider:
        def load(self, ticker: str, cache_only: bool = False):
            return [], [
                contracts.KlineDataStatus(
                    source="openfda",
                    status="rate_limited",
                    item_count=0,
                    message="429 Too Many Requests",
                )
            ]

    service = contracts.KlineWorkspaceService(
        resolver=contracts.TickerResolver(),
        ohlc_provider=FakeOHLCProvider(
            contracts.KlineDataStatus,
            contracts.KlinePriceSeries,
        ),
        catalyst_provider=RateLimitedCatalystProvider(),
        backtest_provider=FakeBacktestProvider(),
    )

    workspace = service.build_workspace("MRNA")

    assert workspace.warnings[0].source == "openfda"
    assert workspace.warnings[0].code == "openfda_rate_limited"
    assert workspace.warnings[0].message == "429 Too Many Requests"


def test_workspace_payload_contains_phase2_layers_and_future_capabilities():
    contracts = _contracts()
    service = _service(contracts)

    payload = service.build_workspace("MRNA").to_dict()

    assert payload["ticker"] == "MRNA"
    assert payload["company"]["name"] == "Moderna, Inc."
    assert [layer["kind"] for layer in payload["layers"]] == [
        "candles",
        "catalysts",
        "news",
        "macro",
        "backtest",
    ]
    assert payload["layers"][1]["points"][0]["ticker"] == "MRNA"
    assert payload["layers"][2]["points"] == []
    assert payload["layers"][3]["points"] == []
    assert {
        "id": "news",
        "enabled": True,
        "phase": 2,
        "label": "News",
    } in payload["capabilities"]
    assert {
        "id": "macro",
        "enabled": True,
        "phase": 2,
        "label": "Macro",
    } in payload["capabilities"]
    assert {
        "id": "range_analysis",
        "enabled": False,
        "phase": 3,
        "label": "Range Analysis",
    } in payload["capabilities"]


def test_workspace_cache_only_mode_delegates_to_cache_only_providers():
    contracts = _contracts()
    service = _service(contracts)

    service.build_workspace("MRNA", cache_only=True)

    assert service.ohlc_provider.requests == [("MRNA", True)]
    assert service.catalyst_provider.requests == [("MRNA", True)]
    assert service.backtest_provider.requests == ["MRNA"]


def test_workspace_backtest_layer_omits_backend_mock_metadata():
    contracts = _contracts()

    class MockBacktestProvider:
        def load_last_run(self, ticker: str):
            return {
                "run_id": "run-1",
                "ticker": ticker,
                "metrics": {"sharpe": 1.2},
                "equity_curve": [{"date": "2026-04-20", "equity": 1.03}],
                "signals": [{"date": "2026-04-20", "signal": 1}],
                "trades": [{"entry_date": "2026-04-20", "exit_date": "2026-04-20"}],
                "exposure_summary": {"exposure_days": 5, "trade_count": 1},
                "risk_parameters": {
                    "stop_loss_pct": -0.08,
                    "max_position_pct": 0.2,
                    "slippage_pct": 0.001,
                    "holding_period_days": 5,
                },
                "factor_attribution": {
                    "active_factor_days": 8,
                    "mean_mock_score": 0.61,
                    "mean_event_factor": 0.32,
                    "mean_liquidity_factor": 0.12,
                },
                "mock_metadata": {
                    "data_mode": "mock",
                    "synthetic": True,
                    "positive_demo_expected": True,
                },
                "strategy": {
                    "id": "mock_multifactor_demo",
                    "data_mode": "mock",
                    "price_basis": "demo_ohlc",
                    "holding_period_days": 5,
                },
            }

    service = contracts.KlineWorkspaceService(
        resolver=contracts.TickerResolver(),
        ohlc_provider=FakeOHLCProvider(
            contracts.KlineDataStatus,
            contracts.KlinePriceSeries,
        ),
        catalyst_provider=FakeCatalystProvider(
            contracts.KlineDataStatus,
            contracts.KlineEvent,
        ),
        backtest_provider=MockBacktestProvider(),
    )

    payload = service.build_workspace("MRNA").to_dict()
    backtest_layer = next(
        layer for layer in payload["layers"] if layer["kind"] == "backtest"
    )
    summary = backtest_layer["summary"]

    assert summary["run_id"] == "run-1"
    assert summary["factor_attribution"]["active_factor_days"] == 8
    assert summary["factor_attribution"]["mean_event_factor"] == 0.32
    assert summary["factor_attribution"]["mean_liquidity_factor"] == 0.12
    assert summary["exposure_summary"] == {"exposure_days": 5, "trade_count": 1}
    assert summary["risk_parameters"] == {
        "stop_loss_pct": -0.08,
        "max_position_pct": 0.2,
        "slippage_pct": 0.001,
        "holding_period_days": 5,
    }
    assert summary["strategy"] == {
        "price_basis": "demo_ohlc",
        "holding_period_days": 5,
    }
    assert "mean_mock_score" not in summary["factor_attribution"]
    assert backtest_layer["series"] == [{"date": "2026-04-20", "equity": 1.03}]

    summary_text = json.dumps(summary, sort_keys=True).lower()
    for forbidden in ["mock", "synthetic", "positive_demo_expected", "data_mode"]:
        assert forbidden not in summary_text


def test_range_context_returns_phase1_price_and_catalyst_summary():
    contracts = _contracts()
    service = _service(contracts)

    context = service.build_range_context(
        "MRNA",
        "2026-04-20",
        "2026-04-20",
    ).to_dict()

    assert context["ticker"] == "MRNA"
    assert context["start_date"] == "2026-04-20"
    assert context["end_date"] == "2026-04-20"
    assert context["catalyst_count"] == 1
    assert context["phase3_ready"] is True


def test_workspace_payload_splits_catalyst_news_and_macro_layers():
    contracts = _contracts()

    class MixedEventProvider:
        def load(self, ticker: str, cache_only: bool = False):
            return [
                contracts.KlineEvent(
                    id="clinical-1",
                    ticker=ticker,
                    date="2026-04-20",
                    type="trial_results_posted",
                    category="clinical",
                    title="Results posted",
                    summary="Results posted",
                    sentiment="positive",
                    priority=1,
                    confidence="high",
                    source="clinicaltrials",
                ),
                contracts.KlineEvent(
                    id="news-1",
                    ticker=ticker,
                    date="2026-04-21",
                    type="market_news",
                    category="news",
                    title="Market news",
                    summary="Market news",
                    sentiment="positive",
                    priority=3,
                    confidence="medium",
                    source="alphavantage",
                ),
                contracts.KlineEvent(
                    id="macro-1",
                    ticker=ticker,
                    date="2026-04-22",
                    type="macro_economic",
                    category="clinical",
                    title="Macro context",
                    summary="Macro context",
                    sentiment="neutral",
                    priority=3,
                    confidence="low",
                    source="gdelt",
                ),
            ], []

    service = contracts.KlineWorkspaceService(
        resolver=contracts.TickerResolver(),
        ohlc_provider=FakeOHLCProvider(
            contracts.KlineDataStatus,
            contracts.KlinePriceSeries,
        ),
        catalyst_provider=MixedEventProvider(),
        backtest_provider=FakeBacktestProvider(),
    )

    payload = service.build_workspace("MRNA").to_dict()
    layers = {layer["kind"]: layer for layer in payload["layers"]}

    assert [layer["kind"] for layer in payload["layers"]] == [
        "candles",
        "catalysts",
        "news",
        "macro",
        "backtest",
    ]
    assert [event["id"] for event in layers["catalysts"]["points"]] == ["clinical-1"]
    assert [event["id"] for event in layers["news"]["points"]] == ["news-1"]
    assert [event["id"] for event in layers["macro"]["points"]] == ["macro-1"]
    assert {
        "id": "news",
        "enabled": True,
        "phase": 2,
        "label": "News",
    } in payload["capabilities"]
    assert {
        "id": "macro",
        "enabled": True,
        "phase": 2,
        "label": "Macro",
    } in payload["capabilities"]
