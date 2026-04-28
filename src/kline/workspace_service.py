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

        layers = [
            _candles_layer(price),
            _catalysts_layer(catalysts),
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
    return KlineLayer(
        id="catalysts",
        kind="catalysts",
        label="Catalysts",
        visible_by_default=True,
        status="ready" if catalysts else "empty",
        points=catalysts,
        summary={"count": len(catalysts)},
    )


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
    for status in statuses:
        if status.status != "error":
            continue
        warnings.append(
            KlineWarning(
                code=f"{status.source}_error",
                message=status.message or f"{status.source} unavailable",
                source=status.source,
            )
        )
    return warnings


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
