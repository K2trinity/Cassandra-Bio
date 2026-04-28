"""Catalyst event provider for K-line workspaces."""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from src.kline.models import KlineDataStatus, KlineEvent


class CatalystEventProvider:
    def __init__(
        self,
        fetch_events: Callable[[str, int], list[dict[str, Any]]] | None = None,
        fetch_statuses: Callable[..., Any] | None = None,
    ):
        if fetch_events is None:
            from src.services.event_ingestion_service import get_events_for_ticker

            fetch_events = get_events_for_ticker
        self.fetch_events = fetch_events
        self.fetch_statuses = fetch_statuses

    def load(self, ticker: str) -> tuple[list[KlineEvent], list[KlineDataStatus]]:
        requested_ticker = str(ticker).strip().upper()
        try:
            raw_events = list(self.fetch_events(requested_ticker, 6) or [])
        except Exception as exc:  # noqa: BLE001 - provider boundary reports status.
            return (
                [],
                [
                    KlineDataStatus(
                        source="catalyst",
                        status="error",
                        item_count=0,
                        message=str(exc),
                    )
                ],
            )

        events = [
            _normalize_event(requested_ticker, raw_event, index)
            for index, raw_event in enumerate(raw_events)
            if isinstance(raw_event, dict)
        ]
        return events, _statuses_for_events(events)


def _normalize_event(ticker: str, raw: dict[str, Any], index: int) -> KlineEvent:
    metadata = _metadata_dict(raw.get("metadata"))
    raw_ticker = raw.get("ticker")
    if raw_ticker is not None and str(raw_ticker).strip().upper() != ticker:
        metadata.setdefault("raw_ticker", raw_ticker)

    price_impact = raw.get("price_impact")
    if price_impact is not None:
        metadata.setdefault("price_impact", price_impact)
    raw_impact = raw.get("impact")
    if raw_impact is not None:
        if "impact" in metadata and metadata["impact"] != raw_impact:
            metadata.setdefault("raw_impact", raw_impact)
        else:
            metadata.setdefault("impact", raw_impact)

    event_type = _string_value(
        raw.get("type")
        or raw.get("event_type")
        or raw.get("category")
        or "catalyst"
    )
    title = _string_value(
        raw.get("title")
        or raw.get("catalyst")
        or raw.get("summary")
        or event_type
    )
    summary = _string_value(raw.get("summary") or raw.get("catalyst") or title)

    return KlineEvent(
        id=_string_value(raw.get("id") or raw.get("event_id") or f"{ticker}-{index + 1}"),
        ticker=ticker,
        date=_string_value(raw.get("date") or raw.get("event_date") or ""),
        type=event_type,
        category=_category_for(raw),
        title=title,
        summary=summary,
        sentiment=_string_value(raw.get("sentiment") or "neutral"),
        priority=_int_value(raw.get("priority"), default=3),
        confidence=_string_value(raw.get("confidence") or "medium"),
        source=_string_value(raw.get("source") or "unknown"),
        source_url=_optional_string(
            raw.get("source_url") or raw.get("url") or raw.get("link")
        ),
        source_ids=_source_ids(raw.get("source_ids")),
        source_entity=_optional_string(raw.get("source_entity")),
        disease_area=_optional_string(raw.get("disease_area")),
        drug_name=_optional_string(raw.get("drug_name") or raw.get("drug")),
        impact_score=_impact_score(raw),
        metadata=metadata,
    )


def _statuses_for_events(events: list[KlineEvent]) -> list[KlineDataStatus]:
    if not events:
        return [KlineDataStatus(source="catalyst", status="empty", item_count=0)]

    counts: OrderedDict[str, int] = OrderedDict()
    for event in events:
        counts[event.source] = counts.get(event.source, 0) + 1

    return [
        KlineDataStatus(source=source, status="ready", item_count=count)
        for source, count in counts.items()
    ]


def _category_for(raw: dict[str, Any]) -> str:
    values = [
        raw.get("category"),
        raw.get("source"),
        raw.get("type"),
        raw.get("event_type"),
        raw.get("title"),
        raw.get("catalyst"),
    ]
    text = " ".join(str(value).lower() for value in values if value is not None)
    if "fda" in text or "regulatory" in text:
        return "regulatory"
    if any(
        token in text
        for token in ("gdelt", "macro", "geopolitical", "trade", "sanctions")
    ):
        return "macro"
    if any(
        token in text
        for token in ("partnership", "financing", "patent", "competitor")
    ):
        return "corporate"
    return "clinical"


def _metadata_dict(value: object) -> dict[str, Any]:
    decoded = _decode_json_if_string(value)
    if isinstance(decoded, dict):
        return dict(decoded)
    if decoded is None:
        return {}
    return {"value": decoded}


def _source_ids(value: object) -> list[str]:
    decoded = _decode_json_if_string(value)
    if decoded is None:
        return []
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    if isinstance(decoded, tuple):
        return [str(item) for item in decoded]
    return [str(decoded)]


def _decode_json_if_string(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _impact_score(raw: dict[str, Any]) -> object:
    for key in ("impact_score", "price_impact", "impact"):
        value = raw.get(key)
        if value is not None:
            return value
    return None


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _string_value(value: object) -> str:
    return str(value) if value is not None else ""


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
