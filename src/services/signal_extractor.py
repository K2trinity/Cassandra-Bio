"""Extract structured biotech events from report text using Gemini."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from loguru import logger

from src.llms import create_report_client


ALLOWED_EVENT_TYPES = {
    "fda_decision",
    "clinical_readout",
    "partnership",
    "financing",
    "patent",
    "competitor",
    "geopolitical",
    "trade_policy",
    "sanctions",
    "regulatory_change",
    "macro_economic",
}

ALLOWED_SENTIMENTS = {"positive", "negative", "neutral"}

IMPACT_TO_PRICE = {
    "high": 0.05,
    "medium": 0.02,
    "low": 0.01,
}


def _normalize_date(raw_date: Any) -> str:
    """Normalize date input to YYYY-MM-DD; fallback to today."""
    if not raw_date:
        return datetime.now().strftime("%Y-%m-%d")

    text = str(raw_date).strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d")

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return datetime.now().strftime("%Y-%m-%d")


def _normalize_event(raw_event: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    """Normalize one extracted event into biotech_events row shape."""
    if not isinstance(raw_event, dict):
        return None

    event_type = str(raw_event.get("event_type") or "regulatory_change").strip().lower()
    if event_type not in ALLOWED_EVENT_TYPES:
        event_type = "regulatory_change"

    sentiment = str(raw_event.get("sentiment") or "neutral").strip().lower()
    if sentiment not in ALLOWED_SENTIMENTS:
        sentiment = "neutral"

    try:
        priority = int(raw_event.get("priority", 3))
    except (TypeError, ValueError):
        priority = 3
    priority = max(1, min(priority, 5))

    catalyst = str(raw_event.get("catalyst") or "Extracted report signal").strip()
    if not catalyst:
        catalyst = "Extracted report signal"

    impact = str(raw_event.get("estimated_impact") or "").strip().lower()
    price_impact = IMPACT_TO_PRICE.get(impact)

    return {
        "id": str(uuid.uuid4()),
        "date": _normalize_date(raw_event.get("date")),
        "type": event_type,
        "priority": priority,
        "ticker": ticker.upper(),
        "disease_area": "",
        "catalyst": catalyst,
        "sentiment": sentiment,
        "price_impact": price_impact,
        "source": "cassandra_report",
    }


def extract_report_events(report_text: str, ticker: str) -> list[dict]:
    """Extract structured trading events from completed report text."""
    if not report_text or not str(report_text).strip():
        return []
    if not ticker or not str(ticker).strip():
        return []

    client = create_report_client()
    prompt = (
        "Extract biotech market-moving events from the report. Return strict JSON with key 'events'. "
        "Each event must include: event_type, sentiment, priority, catalyst, estimated_impact, date.\n\n"
        f"Ticker: {ticker.upper()}\n"
        f"Report:\n{report_text}"
    )
    schema = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string"},
                        "sentiment": {"type": "string"},
                        "priority": {"type": "integer"},
                        "catalyst": {"type": "string"},
                        "estimated_impact": {"type": "string"},
                        "date": {"type": "string"},
                    },
                    "required": ["event_type", "sentiment", "priority", "catalyst", "date"],
                },
            }
        },
        "required": ["events"],
    }

    try:
        payload = client.generate_json(prompt, response_schema=schema)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Signal extraction failed: {exc}")
        return []

    if not isinstance(payload, dict):
        return []

    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        return []

    normalized: list[dict] = []
    for raw_event in raw_events:
        event = _normalize_event(raw_event, ticker=ticker)
        if event:
            normalized.append(event)

    return normalized
