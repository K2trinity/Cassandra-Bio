"""OHLC price provider for K-line workspaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.kline.models import KlineDataStatus, KlinePriceSeries


class OHLCProvider:
    def __init__(self, fetch_rows: Callable[[str, int], Any] | None = None):
        if fetch_rows is None:
            from src.services.market_data_service import get_ohlc_rows_with_status

            fetch_rows = get_ohlc_rows_with_status
        self.fetch_rows = fetch_rows

    def load(self, ticker: str) -> tuple[KlinePriceSeries, list[KlineDataStatus]]:
        try:
            rows, status, message, last_updated = _rows_status_from_payload(
                self.fetch_rows(ticker, 24)
            )
            status = status or ("ready" if rows else "empty")

            if not rows:
                return (
                    KlinePriceSeries.empty(cache_status=status),
                    [
                        KlineDataStatus(
                            source="ohlc",
                            status=status,
                            item_count=0,
                            message=message,
                        )
                    ],
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
                cache_status=status,
                last_updated=last_updated,
            )
            return (
                price,
                [
                    KlineDataStatus(
                        source="ohlc",
                        status=status,
                        item_count=len(rows),
                        message=message,
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary reports status.
            return _error_result(exc)


def _rows_status_from_payload(
    payload: object,
) -> tuple[list[Any], str | None, str | None, str | None]:
    if isinstance(payload, dict):
        rows = list(payload.get("rows") or [])
        return (
            rows,
            _optional_string(payload.get("status")),
            _optional_string(payload.get("message")),
            _optional_string(payload.get("last_updated")),
        )
    return list(payload or []), None, None, None


def _date_value(row: dict[str, Any]) -> str | None:
    value = row.get("date")
    return str(value) if value is not None else None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _number_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _error_result(exc: Exception) -> tuple[KlinePriceSeries, list[KlineDataStatus]]:
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
