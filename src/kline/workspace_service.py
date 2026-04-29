"""Service layer for K-line workspace payloads."""

from __future__ import annotations

from typing import Any

from src.kline.models import (
    KlineDataStatus,
    KlineEvent,
    KlineLayer,
    KlinePanelState,
    KlinePriceSeries,
    KlineRangeContext,
    KlineWarning,
    KlineWorkspacePayload,
    disabled_future_capabilities,
)
from src.kline.providers.backtest_provider import BacktestResultProvider
from src.kline.providers.catalyst_provider import CatalystEventProvider
from src.kline.providers.ohlc_provider import OHLCProvider
from src.kline.ticker_resolver import TickerResolver

_MARKET_NEWS_SOURCES = {"alphavantage", "alpha_vantage", "market_news", "news"}
_MACRO_SOURCES = {"gdelt", "fred", "worldbank", "macro"}


class KlineWorkspaceService:
    def __init__(
        self,
        resolver: TickerResolver | None = None,
        ohlc_provider: OHLCProvider | None = None,
        catalyst_provider: CatalystEventProvider | None = None,
        backtest_provider: BacktestResultProvider | None = None,
    ):
        self.resolver = resolver or TickerResolver()
        self.ohlc_provider = ohlc_provider or OHLCProvider()
        self.catalyst_provider = catalyst_provider or CatalystEventProvider()
        self.backtest_provider = backtest_provider or BacktestResultProvider()

    def build_workspace(self, symbol: object) -> KlineWorkspacePayload:
        company = self.resolver.resolve(symbol)
        ticker = company.ticker

        price, price_statuses = self.ohlc_provider.load(ticker)
        catalysts, catalyst_statuses = self.catalyst_provider.load(ticker)
        last_backtest = self.backtest_provider.load_last_run(ticker)

        backtest_status = "ready" if last_backtest else "empty"
        backtest_statuses = [
            KlineDataStatus(
                source="backtest",
                status=backtest_status,
                item_count=1 if last_backtest else 0,
            )
        ]

        hard_events, news_events, macro_events = _split_event_layers(catalysts)
        layers = [
            _candles_layer(price),
            _events_layer("catalysts", "catalysts", "Catalysts", hard_events, True),
            _events_layer("news", "news", "News", news_events, True),
            _events_layer("macro", "macro", "Macro", macro_events, False),
            _backtest_layer(last_backtest),
        ]
        data_status = price_statuses + catalyst_statuses + backtest_statuses

        return KlineWorkspacePayload(
            ticker=ticker,
            company=company,
            price=price,
            layers=layers,
            panels=KlinePanelState(
                active_panel="catalysts",
                last_backtest_run_id=_run_id(last_backtest),
            ),
            data_status=data_status,
            warnings=_warnings_from_statuses(data_status),
            capabilities=disabled_future_capabilities(),
        )

    def build_range_context(
        self,
        symbol: object,
        start_date: str,
        end_date: str,
    ) -> KlineRangeContext:
        company = self.resolver.resolve(symbol)
        ticker = company.ticker
        price, _price_statuses = self.ohlc_provider.load(ticker)
        catalysts, _catalyst_statuses = self.catalyst_provider.load(ticker)

        price_rows = sorted(
            [
                row
                for row in price.rows
                if _date_in_range(row.get("date"), start_date, end_date)
            ],
            key=lambda row: str(row.get("date") or ""),
        )
        matching_catalysts = [
            event
            for event in catalysts
            if _date_in_range(event.date, start_date, end_date)
        ]

        return KlineRangeContext(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            price_change_pct=_price_change_pct(price_rows),
            catalyst_count=len(matching_catalysts),
            catalysts=matching_catalysts,
            phase3_ready=True,
        )


def _candles_layer(price: KlinePriceSeries) -> KlineLayer:
    return KlineLayer(
        id="candles",
        kind="candles",
        label="Candles",
        visible_by_default=True,
        status="ready" if price.rows else "empty",
        series=price.rows,
        summary={
            "date_range": price.date_range,
            "last_close": price.last_close,
            "cache_status": price.cache_status,
        },
    )


def _catalysts_layer(catalysts: list[KlineEvent]) -> KlineLayer:
    return _events_layer("catalysts", "catalysts", "Catalysts", catalysts, True)


def _events_layer(
    layer_id: str,
    kind: str,
    label: str,
    events: list[KlineEvent],
    visible_by_default: bool,
) -> KlineLayer:
    return KlineLayer(
        id=layer_id,
        kind=kind,
        label=label,
        visible_by_default=visible_by_default,
        status="ready" if events else "empty",
        points=events,
        summary={"count": len(events)},
    )


def _split_event_layers(
    events: list[KlineEvent],
) -> tuple[list[KlineEvent], list[KlineEvent], list[KlineEvent]]:
    hard_events: list[KlineEvent] = []
    news_events: list[KlineEvent] = []
    macro_events: list[KlineEvent] = []
    for event in events:
        kind = _event_layer_kind(event)
        if kind == "news":
            news_events.append(event)
        elif kind == "macro":
            macro_events.append(event)
        else:
            hard_events.append(event)
    return hard_events, news_events, macro_events


def _event_layer_kind(event: KlineEvent) -> str:
    category = _normalized_token(event.category)
    source = _normalized_token(event.source)
    source_tier = _normalized_token(event.source_tier)
    source_kind = _normalized_token(event.source_kind)
    event_type = _normalized_token(event.type)
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    metadata_tier = _normalized_token(metadata.get("source_tier"))
    metadata_kind = _normalized_token(metadata.get("source_kind"))

    if (
        category == "macro"
        or source_tier == "macro"
        or source_kind == "macro"
        or metadata_tier == "macro"
        or metadata_kind == "macro"
        or source in _MACRO_SOURCES
        or event_type.startswith("macro_")
    ):
        return "macro"
    if (
        category == "news"
        or source_tier in {"market_news", "news"}
        or source_kind in {"market_news", "news"}
        or metadata_tier in {"market_news", "news"}
        or metadata_kind in {"market_news", "news"}
        or source in _MARKET_NEWS_SOURCES
        or event_type in {"market_news", "news"}
    ):
        return "news"
    return "catalysts"


def _normalized_token(value: object) -> str:
    return str(value or "").strip().lower()


def _backtest_layer(last_backtest: dict[str, Any] | None) -> KlineLayer:
    return KlineLayer(
        id="backtest",
        kind="backtest",
        label="Backtest",
        visible_by_default=False,
        status="ready" if last_backtest else "empty",
        series=_backtest_series(last_backtest),
        summary=last_backtest or {},
    )


def _backtest_series(last_backtest: dict[str, Any] | None) -> list[Any]:
    if not last_backtest:
        return []
    series = last_backtest.get("equity_curve")
    return series if isinstance(series, list) else []


def _warnings_from_statuses(statuses: list[KlineDataStatus]) -> list[KlineWarning]:
    warnings: list[KlineWarning] = []
    warning_statuses = {"error", "rate_limited", "stale"}
    for status in statuses:
        if status.status not in warning_statuses:
            continue
        warnings.append(
            KlineWarning(
                code=f"{status.source}_{status.status}",
                message=status.message or _status_message(status),
                source=status.source,
            )
        )
    return warnings


def _status_message(status: KlineDataStatus) -> str:
    if status.status == "rate_limited":
        return f"{status.source} rate limited"
    if status.status == "stale":
        return f"{status.source} using stale cached data"
    return f"{status.source} unavailable"


def _run_id(last_backtest: dict[str, Any] | None) -> str | None:
    if not last_backtest:
        return None
    run_id = last_backtest.get("run_id")
    return str(run_id) if run_id is not None else None


def _date_in_range(value: object, start_date: str, end_date: str) -> bool:
    if value is None:
        return False
    date_value = str(value)
    return start_date <= date_value <= end_date


def _price_change_pct(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None

    first_open = _number_or_none(rows[0].get("open"))
    last_close = _number_or_none(rows[-1].get("close"))
    if first_open in (None, 0) or last_close is None:
        return None

    return round(((last_close - first_open) / first_open) * 100, 4)


def _number_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
