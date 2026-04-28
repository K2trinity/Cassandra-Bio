from types import SimpleNamespace


def _contracts():
    from src.services.kline_workspace_service import (
        CatalystEventProvider,
        KlineDataStatus,
        KlineEvent,
        KlinePriceSeries,
        KlineWorkspaceService,
        TickerResolver,
    )

    return SimpleNamespace(
        CatalystEventProvider=CatalystEventProvider,
        KlineDataStatus=KlineDataStatus,
        KlineEvent=KlineEvent,
        KlinePriceSeries=KlinePriceSeries,
        KlineWorkspaceService=KlineWorkspaceService,
        TickerResolver=TickerResolver,
    )


class FakeRawCatalystProvider:
    def __init__(self, events):
        self.events = events
        self.requests = []

    def get_events_for_ticker(self, ticker, start_date=None, end_date=None):
        self.requests.append(
            {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return list(self.events)


class FakePriceProvider:
    def __init__(self, price_series):
        self.price_series = price_series
        self.requests = []

    def get_series(self, ticker):
        self.requests.append(ticker)
        return self.price_series


class FakeCatalystProvider:
    def __init__(self, events):
        self.events = events
        self.requests = []

    def get_events(self, ticker, start_date=None, end_date=None):
        self.requests.append(
            {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        events = list(self.events)
        if start_date is not None:
            events = [event for event in events if event.date >= start_date]
        if end_date is not None:
            events = [event for event in events if event.date <= end_date]
        return events


def _sample_event(KlineEvent, ticker="MRNA"):
    return KlineEvent(
        id="clinicaltrials:NCT00000001",
        date="2026-04-20",
        type="clinical_readout",
        priority=4,
        ticker=ticker,
        disease_area="Respiratory Syncytial Virus",
        catalyst="Phase 3 readout posted",
        sentiment="positive",
        source="clinicaltrials",
        source_entity="ModernaTX, Inc.",
        source_ids=["NCT00000001"],
        metadata={"phase": "Phase 3"},
    )


def _sample_price_series(KlineDataStatus, KlinePriceSeries):
    return KlinePriceSeries(
        ticker="MRNA",
        status=KlineDataStatus.READY,
        candles=[
            {
                "date": "2026-04-20",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 1200000,
            }
        ],
        source="fake-market-data",
    )


def test_ticker_resolver_resolves_biotech_ticker_contract():
    contracts = _contracts()

    resolved = contracts.TickerResolver.resolve(" mrna ")

    assert resolved.ticker == "MRNA"
    assert resolved.name == "Moderna, Inc."
    assert resolved.is_biotech is True


def test_ticker_resolver_rejects_path_like_symbols():
    contracts = _contracts()

    assert contracts.TickerResolver.normalize("../MRNA") is None


def test_catalyst_event_provider_preserves_requested_ticker_ownership():
    contracts = _contracts()
    raw_events = [
        {
            "id": "clinicaltrials:NCT00000001",
            "date": "2026-04-20",
            "type": "clinical_readout",
            "priority": 4,
            "ticker": "ModernaTX,",
            "disease_area": "Respiratory Syncytial Virus",
            "catalyst": "Phase 3 readout posted",
            "sentiment": "positive",
            "source": "clinicaltrials",
            "source_entity": "ModernaTX, Inc.",
            "source_ids": ["NCT00000001"],
        }
    ]
    raw_provider = FakeRawCatalystProvider(raw_events)
    provider = contracts.CatalystEventProvider(raw_provider)

    events = provider.get_events("MRNA")

    assert raw_provider.requests == [
        {"ticker": "MRNA", "start_date": None, "end_date": None}
    ]
    assert len(events) == 1
    assert events[0].ticker == "MRNA"
    assert events[0].source_entity == "ModernaTX, Inc."
    assert events[0].source_ids == ["NCT00000001"]


def test_kline_workspace_service_builds_phase1_workspace_payload():
    contracts = _contracts()
    price_series = _sample_price_series(
        contracts.KlineDataStatus,
        contracts.KlinePriceSeries,
    )
    catalyst_event = _sample_event(contracts.KlineEvent)
    service = contracts.KlineWorkspaceService(
        ticker_resolver=contracts.TickerResolver,
        price_provider=FakePriceProvider(price_series),
        catalyst_provider=FakeCatalystProvider([catalyst_event]),
    )

    payload = service.build_workspace("MRNA").to_dict()

    assert payload["ticker"] == "MRNA"
    assert payload["company"] == "Moderna, Inc."
    assert payload["layers"] == ["candles", "catalysts", "backtest"]
    assert payload["catalysts"]["events"][0]["ticker"] == "MRNA"
    assert payload["capabilities"]["news"]["enabled"] is False
    assert payload["capabilities"]["news"]["phase"] == 2
    assert payload["capabilities"]["range_analysis"]["enabled"] is False
    assert payload["capabilities"]["range_analysis"]["phase"] == 3


def test_kline_workspace_service_builds_phase3_range_context():
    contracts = _contracts()
    price_series = _sample_price_series(
        contracts.KlineDataStatus,
        contracts.KlinePriceSeries,
    )
    catalyst_event = _sample_event(contracts.KlineEvent)
    service = contracts.KlineWorkspaceService(
        ticker_resolver=contracts.TickerResolver,
        price_provider=FakePriceProvider(price_series),
        catalyst_provider=FakeCatalystProvider([catalyst_event]),
    )

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
