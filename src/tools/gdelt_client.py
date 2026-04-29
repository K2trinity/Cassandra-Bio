"""GDELT client for biotech-relevant macro and geopolitical events."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import hashlib

import requests
from loguru import logger

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _normalize_date(raw_value: Any) -> str | None:
    if raw_value is None:
        return None

    text = str(raw_value).strip()
    if not text:
        return None

    formats = [
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def _infer_event_type(text: str) -> str:
    body = text.lower()

    sanctions_keywords = [
        "sanction",
        "embargo",
        "blacklist",
        "export control",
        "restricted entity",
    ]
    if any(keyword in body for keyword in sanctions_keywords):
        return "sanctions"

    trade_keywords = [
        "trade policy",
        "tariff",
        "import duty",
        "export duty",
        "trade agreement",
        "supply chain rule",
    ]
    if any(keyword in body for keyword in trade_keywords):
        return "trade_policy"

    geopolitical_keywords = [
        "geopolitical",
        "war",
        "conflict",
        "diplomatic",
        "border tension",
        "election risk",
    ]
    if any(keyword in body for keyword in geopolitical_keywords):
        return "geopolitical"

    macro_keywords = [
        "inflation",
        "interest rate",
        "gdp",
        "recession",
        "macro",
        "central bank",
        "economic slowdown",
    ]
    if any(keyword in body for keyword in macro_keywords):
        return "macro_economic"

    return "macro_economic"


def _infer_sentiment(article: dict[str, Any]) -> str:
    tone = article.get("tone")
    try:
        score = float(tone)
    except (TypeError, ValueError):
        score = 0.0

    if score > 1.0:
        return "positive"
    if score < -1.0:
        return "negative"
    return "neutral"


def fetch_biotech_macro_events(
    query: str,
    max_records: int = 20,
    raise_on_error: bool = False,
) -> list[dict]:
    """Fetch and normalize biotech-related macro events from GDELT."""
    search_query = (
        f"({query}) AND (biotech OR pharmaceutical OR pharma OR vaccine OR drug)"
    )
    params = {
        "query": search_query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max(1, min(int(max_records), 100)),
        "sort": "DateDesc",
    }

    try:
        response = requests.get(GDELT_DOC_API, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"GDELT fetch failed for query '{query}': {exc}")
        if raise_on_error:
            raise
        return []

    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        return []

    events: list[dict] = []
    for article in articles:
        if not isinstance(article, dict):
            continue

        title = str(article.get("title") or "").strip()
        summary = str(article.get("snippet") or "").strip()
        if not summary:
            summary = title
        if not summary:
            continue

        event_date = _normalize_date(
            article.get("seendate") or article.get("date") or article.get("published")
        )
        if not event_date:
            continue

        url = str(article.get("url") or "").strip()
        source_country = str(article.get("sourcecountry") or "").strip()
        context_text = " ".join(
            [
                title,
                summary,
                url,
                source_country,
            ]
        )
        event_type = _infer_event_type(context_text)

        if event_type == "sanctions":
            priority = 2
        elif event_type == "trade_policy":
            priority = 2
        elif event_type == "geopolitical":
            priority = 3
        else:
            priority = 3

        event_id_basis = f"{url}|{event_date}|{summary}".encode(
            "utf-8", errors="ignore"
        )
        event_id = "gdelt-" + hashlib.sha1(event_id_basis).hexdigest()[:16]

        events.append(
            {
                "id": event_id,
                "date": event_date,
                "type": event_type,
                "priority": priority,
                "ticker": query.upper(),
                "disease_area": "",
                "catalyst": summary[:500],
                "sentiment": _infer_sentiment(article),
                "price_impact": None,
                "source": "gdelt",
            }
        )

    return events
