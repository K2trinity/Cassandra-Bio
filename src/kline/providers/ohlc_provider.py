"""OHLC price provider for K-line workspaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.kline.models import KlineDataStatus, KlinePriceSeries


class OHLCProvider:
    def __init__(self, fetch_rows: Callable[[str, int], list[dict[str, Any]]] | None = None):
        if fetch_rows is None:
            from src.services.market_data_service import get_ohlc_rows

            fetch_rows = get_ohlc_rows
        self.fetch_rows = fetch_rows

    def load(self, ticker: str) -> tuple[KlinePriceSeries, list[KlineDataStatus]]:
        try:
            rows = list(self.fetch_rows(ticker, 24) or [])
        except Exception as exc:  # noqa: BLE001 - provider boundary reports status.
            return (
                KlinePriceSeries.empty(cache_status="error"),
                [
                    KlineDataStatus(
                        source="ohlc",
                        status="error",
                        item_count=0,
                        message=str(exc),
                    )
                ],
            )

        if not rows:
            return (
                KlinePriceSeries.empty(cache_status="empty"),
                [KlineDataStatus(source="ohlc", status="empty", item_count=0)],
            )

        last_row = rows[-1]
        dates = [_date_value(row) for row in rows]
        dates = [date for date in dates if date is not None]
        price = KlinePriceSeries(
            rows=rows,
            date_range={
                "start": min(dates) if dates else None,
                "end": max(dates) if dates else None,
            },
            last_close=_number_or_none(last_row.get("close")),
            cache_status="ready",
            last_updated=None,
        )
        return (
            price,
            [KlineDataStatus(source="ohlc", status="ready", item_count=len(rows))],
        )


def _date_value(row: dict[str, Any]) -> str | None:
    value = row.get("date")
    return str(value) if value is not None else None


def _number_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
