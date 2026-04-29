"""K-line workspace data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class _DataclassDictMixin:
    """Small JSON-oriented serializer for dataclass contracts."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KlineCompany(_DataclassDictMixin):
    ticker: str
    name: str
    aliases: list[str] = field(default_factory=list)
    sector: str = "Healthcare"
    is_biotech: bool = False

    @classmethod
    def example(cls, ticker: str = "MRNA") -> "KlineCompany":
        return cls(
            ticker=ticker.upper(),
            name="Moderna, Inc." if ticker.upper() == "MRNA" else ticker.upper(),
            aliases=["ModernaTX, Inc."] if ticker.upper() == "MRNA" else [],
            is_biotech=ticker.upper() == "MRNA",
        )


@dataclass
class KlinePriceSeries(_DataclassDictMixin):
    rows: list[dict[str, Any]]
    date_range: dict[str, str | None]
    last_close: float | None
    cache_status: str
    last_updated: str | None = None

    @classmethod
    def empty(cls, cache_status: str = "empty") -> "KlinePriceSeries":
        return cls(
            rows=[],
            date_range={"start": None, "end": None},
            last_close=None,
            cache_status=cache_status,
            last_updated=None,
        )

    @classmethod
    def example(cls) -> "KlinePriceSeries":
        return cls(
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
        )


@dataclass
class KlineDataStatus(_DataclassDictMixin):
    source: str
    status: str
    item_count: int
    last_fetch_at: str | None = None
    message: str | None = None


@dataclass
class KlineWarning(_DataclassDictMixin):
    code: str
    message: str
    source: str | None = None


@dataclass
class KlineCapability(_DataclassDictMixin):
    id: str
    enabled: bool
    phase: int
    label: str


@dataclass
class KlineEvent(_DataclassDictMixin):
    id: str
    ticker: str
    date: str
    type: str
    category: str
    title: str
    summary: str
    sentiment: str
    priority: int
    confidence: str
    source: str
    source_url: str | None = None
    source_ids: list[str] = field(default_factory=list)
    source_entity: str | None = None
    disease_area: str | None = None
    drug_name: str | None = None
    impact_score: float | int | str | None = None
    source_tier: str | None = None
    source_kind: str | None = None
    confidence_score: float | int | None = None
    backtest_eligible: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def example(cls, ticker: str = "MRNA") -> "KlineEvent":
        return cls(
            id="evt-1",
            ticker=ticker.upper(),
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
        )


@dataclass
class KlineLayer(_DataclassDictMixin):
    id: str
    kind: str
    label: str
    visible_by_default: bool
    status: str
    points: list[Any] = field(default_factory=list)
    series: list[Any] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class KlinePanelState(_DataclassDictMixin):
    active_panel: str = "catalysts"
    selected_event_id: str | None = None
    last_backtest_run_id: str | None = None


def disabled_future_capabilities() -> list[KlineCapability]:
    return [
        KlineCapability(id="news", enabled=True, phase=2, label="News"),
        KlineCapability(id="macro", enabled=True, phase=2, label="Macro"),
        KlineCapability(id="forecast", enabled=False, phase=3, label="Forecast"),
        KlineCapability(
            id="range_analysis",
            enabled=False,
            phase=3,
            label="Range Analysis",
        ),
    ]


@dataclass
class KlineWorkspacePayload(_DataclassDictMixin):
    ticker: str
    company: KlineCompany
    price: KlinePriceSeries
    layers: list[KlineLayer]
    panels: KlinePanelState
    data_status: list[KlineDataStatus]
    warnings: list[KlineWarning]
    capabilities: list[KlineCapability]

    @classmethod
    def example(cls, symbol: str = "MRNA") -> "KlineWorkspacePayload":
        ticker = symbol.strip().upper()
        company = KlineCompany.example(ticker)
        price = KlinePriceSeries.example()
        event = KlineEvent.example(ticker)
        return cls(
            ticker=ticker,
            company=company,
            price=price,
            layers=[
                KlineLayer(
                    id="candles",
                    kind="candles",
                    label="Candles",
                    visible_by_default=True,
                    status="ready",
                    series=price.rows,
                ),
                KlineLayer(
                    id="catalysts",
                    kind="catalysts",
                    label="Catalysts",
                    visible_by_default=True,
                    status="ready",
                    points=[event],
                ),
                KlineLayer(
                    id="backtest",
                    kind="backtest",
                    label="Backtest",
                    visible_by_default=False,
                    status="empty",
                ),
            ],
            panels=KlinePanelState(),
            data_status=[
                KlineDataStatus(source="ohlc", status="ready", item_count=1),
                KlineDataStatus(
                    source="clinicaltrials",
                    status="ready",
                    item_count=1,
                ),
                KlineDataStatus(source="backtest", status="empty", item_count=0),
            ],
            warnings=[],
            capabilities=disabled_future_capabilities(),
        )


@dataclass
class KlineRangeContext(_DataclassDictMixin):
    ticker: str
    start_date: str
    end_date: str
    price_change_pct: float | None
    catalyst_count: int
    catalysts: list[KlineEvent]
    phase3_ready: bool = True
