from types import SimpleNamespace


def _contracts():
    from src.kline.models import KlineDataStatus, KlineEvent, KlinePriceSeries
    from src.kline.providers.catalyst_provider import CatalystEventProvider
    from src.kline.ticker_resolver import TickerResolver
    from src.kline.workspace_service import KlineWorkspaceService

    return SimpleNamespace(
        CatalystEventProvider=CatalystEventProvider,
        KlineDataStatus=KlineDataStatus,
        KlineEvent=KlineEvent,
        KlinePriceSeries=KlinePriceSeries,
        KlineWorkspaceService=KlineWorkspaceService,
        TickerResolver=TickerResolver,
    )


class FakeOHLCProvider:
    def __init__(self, KlineDataStatus, KlinePriceSeries):
        self.KlineDataStatus = KlineDataStatus
        self.KlinePriceSeries = KlinePriceSeries
        self.requests = []

    def load(self, ticker: str):
        self.requests.append(ticker)
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

    def load(self, ticker: str):
        self.requests.append(ticker)
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


def test_ticker_resolver_rejects_path_like_symbols():
    contracts = _contracts()
    resolver = contracts.TickerResolver()

    assert resolver.normalize("../MRNA") is None


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
        ]
    )

    events, statuses = provider.load("MRNA")

    assert events[0].ticker == "MRNA"
    assert events[0].source_entity == "ModernaTX, Inc."
    assert events[0].source_ids == ["NCT00000001"]
    assert statuses[0].source == "clinicaltrials"
    assert statuses[0].status == "ready"


def test_workspace_payload_contains_phase1_layers_and_disabled_future_capabilities():
    contracts = _contracts()
    service = _service(contracts)

    payload = service.build_workspace("MRNA").to_dict()

    assert payload["ticker"] == "MRNA"
    assert payload["company"]["name"] == "Moderna, Inc."
    assert [layer["kind"] for layer in payload["layers"]] == [
        "candles",
        "catalysts",
        "backtest",
    ]
    assert payload["layers"][1]["points"][0]["ticker"] == "MRNA"
    assert {
        "id": "news",
        "enabled": False,
        "phase": 2,
        "label": "News",
    } in payload["capabilities"]
    assert {
        "id": "range_analysis",
        "enabled": False,
        "phase": 3,
        "label": "Range Analysis",
    } in payload["capabilities"]


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
