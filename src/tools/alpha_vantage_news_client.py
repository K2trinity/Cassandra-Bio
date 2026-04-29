"""Alpha Vantage NEWS_SENTIMENT client for Kline market-news events."""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from typing import Any

import requests
from loguru import logger

from src.kline.event_filter import enrich_event_metadata

ALPHA_VANTAGE_NEWS_URL = "https://www.alphavantage.co/query"
DEFAULT_TOPICS = "life_sciences,mergers_and_acquisitions,earnings,financial_markets"


def fetch_market_news_events(
    ticker: str,
    *,
    start: str | None = None,
    end: str | None = None,
    topics: str | list[str] | tuple[str, ...] | None = None,
    limit: int = 100,
    api_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and normalize Alpha Vantage NEWS_SENTIMENT events for a ticker."""
    key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return [], {
            "source": "alphavantage",
            "status": "disabled",
            "item_count": 0,
            "message": "ALPHA_VANTAGE_API_KEY is not set",
        }

    params: dict[str, Any] = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker.strip().upper(),
        "topics": _topics_param(topics),
        "limit": max(1, min(int(limit), 1000)),
        "apikey": key,
    }
    if start:
        params["time_from"] = _to_alpha_time(start)
    if end:
        params["time_to"] = _to_alpha_time(end, end_of_day=True)

    try:
        response = requests.get(ALPHA_VANTAGE_NEWS_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Alpha Vantage news fetch failed for {ticker}: {exc}")
        return [], {
            "source": "alphavantage",
            "status": _status_for_exception(exc),
            "item_count": 0,
            "message": str(exc),
        }

    api_message = _api_message(payload)
    if api_message:
        status = (
            "rate_limited"
            if "frequency" in api_message.lower() or "rate" in api_message.lower()
            else "error"
        )
        return [], {
            "source": "alphavantage",
            "status": status,
            "item_count": 0,
            "message": api_message,
        }

    events = normalize_news_sentiment_feed(payload, requested_ticker=ticker)
    return events, {
        "source": "alphavantage",
        "status": "ready" if events else "empty",
        "item_count": len(events),
        "message": None,
    }


def normalize_news_sentiment_feed(
    payload: dict[str, Any],
    requested_ticker: str,
) -> list[dict[str, Any]]:
    """Normalize Alpha Vantage NEWS_SENTIMENT feed rows to Cassandra event schema."""
    feed = payload.get("feed", []) if isinstance(payload, dict) else []
    if not isinstance(feed, list):
        return []

    events: list[dict[str, Any]] = []
    ticker = requested_ticker.strip().upper()
    for article in feed:
        if not isinstance(article, dict):
            continue
        ticker_sentiment = _ticker_sentiment(article, ticker)
        relevance = _float_value(ticker_sentiment.get("relevance_score"), 0.0)
        if relevance < 0.30:
            continue

        date = _normalize_alpha_date(article.get("time_published"))
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        summary = str(article.get("summary") or title).strip()
        if not date or not title:
            continue

        event_type = _infer_news_type(" ".join([title, summary]))
        sentiment_score = _float_value(
            ticker_sentiment.get("ticker_sentiment_score"),
            _float_value(article.get("overall_sentiment_score"), 0.0),
        )
        metadata = {
            "raw_type": "NEWS_SENTIMENT",
            "source_name": article.get("source"),
            "topics": article.get("topics") or [],
            "ticker_relevance_score": relevance,
            "ticker_sentiment_score": sentiment_score,
            "entity_match": "ticker",
        }
        event = {
            "id": "av-"
            + hashlib.sha1(
                f"{ticker}|{url or title}|{date}".encode("utf-8", errors="ignore")
            ).hexdigest()[:16],
            "date": date,
            "type": event_type,
            "category": "news",
            "priority": _priority_from_news(event_type, relevance),
            "ticker": ticker,
            "disease_area": "",
            "catalyst": title,
            "title": title,
            "summary": summary[:600],
            "sentiment": _sentiment_from_score(sentiment_score),
            "price_impact": None,
            "source": "alphavantage",
            "source_entity": article.get("source"),
            "source_url": url or None,
            "source_ids": [url] if url else [],
            "confidence": "medium",
            "metadata": metadata,
        }
        events.append(enrich_event_metadata(event))
    return events


def _topics_param(topics: str | list[str] | tuple[str, ...] | None) -> str:
    if topics is None:
        return DEFAULT_TOPICS
    if isinstance(topics, str):
        return topics
    return ",".join(str(topic).strip() for topic in topics if str(topic).strip())


def _to_alpha_time(value: str, end_of_day: bool = False) -> str:
    suffix = "T2359" if end_of_day else "T0000"
    return value.replace("-", "") + suffix


def _normalize_alpha_date(value: object) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _ticker_sentiment(article: dict[str, Any], ticker: str) -> dict[str, Any]:
    rows = article.get("ticker_sentiment") or []
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == ticker:
            return row
    return {}


def _infer_news_type(text: str) -> str:
    body = text.lower()
    if any(
        token in body
        for token in (
            "merger",
            "acquisition",
            "m&a",
            "partnership",
            "collaboration",
            "license",
            "licensing",
            "deal",
        )
    ):
        return "partnership_mna"
    if any(
        token in body
        for token in (
            "earnings",
            "offering",
            "financing",
            "debt",
            "cash runway",
            "guidance",
        )
    ):
        return "earnings_financing"
    if any(
        token in body
        for token in ("analyst", "upgrade", "downgrade", "price target", "rating")
    ):
        return "analyst_news"
    return "market_news"


def _priority_from_news(event_type: str, relevance: float) -> int:
    if event_type in {"partnership_mna", "earnings_financing"} and relevance >= 0.70:
        return 2
    return 3


def _sentiment_from_score(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


def _float_value(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _api_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "Unexpected Alpha Vantage response payload"
    for key in ("Note", "Information", "Error Message"):
        if payload.get(key):
            return str(payload[key])
    return None


def _status_for_exception(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "rate" in text or "too many requests" in text:
        return "rate_limited"
    return "error"
