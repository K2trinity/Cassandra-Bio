# Kline Phase 2 Multisource Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multisource biotech event pipeline for Kline with Alpha Vantage news, richer ClinicalTrials milestones, confidence-based filtering, backtest diagnostics, and separate chart layers for catalysts/news/macro.

**Architecture:** Keep the existing Kline vertical slice and SQLite event store. Add a small event scoring/filter module that every source can use, then route scored events into existing providers, backtest signals, and workspace layers without introducing a new evidence warehouse.

**Tech Stack:** Python 3.11, Flask, pandas, SQLite, pytest, TypeScript/React/D3 chart bundle, browser static JavaScript tests through Node.

---

## File Structure

- Create `src/kline/event_filter.py`: event taxonomy, score normalization, backtest eligibility, dedupe keys, and event filtering.
- Create `tests/test_kline_event_filter.py`: behavior tests for scoring and eligibility.
- Create `src/tools/alpha_vantage_news_client.py`: Alpha Vantage `NEWS_SENTIMENT` client and normalizer.
- Create `tests/test_alpha_vantage_news_client.py`: client and normalization tests with mocked HTTP/env.
- Modify `src/tools/clinical_trials_client.py`: add milestone event expansion while keeping legacy normalizer behavior intact.
- Modify `src/services/event_ingestion_service.py`: ingest Alpha Vantage as optional news source and use milestone ClinicalTrials events.
- Modify `tests/test_event_ingestion_service.py`: cover Alpha Vantage status handling and ClinicalTrials milestone expansion.
- Create `src/backtest/attribution.py`: event filtering summary, attribution summaries, signal summary, and buy-hold baseline helpers.
- Modify `src/backtest/signals.py`: use scored/eligible events while preserving the current return shape.
- Modify `src/backtest/runner.py`: return phase2 diagnostics.
- Modify `tests/test_kline_backtest_runner.py`: cover diagnostics and default eligible-event filtering.
- Modify `src/kline/models.py`: enable phase2 `news` and `macro` capabilities.
- Modify `src/kline/workspace_service.py`: split event points into `catalysts`, `news`, and `macro` layers.
- Modify `src/kline/providers/catalyst_provider.py`: expose metadata-derived category, confidence score, impact score, and backtest eligibility.
- Modify `static/kline/workspace.js`: combine active event layers, render layer toggles generically, and render backtest diagnostics.
- Modify `tests/test_kline_workspace_service.py`: verify phase2 layers.
- Modify `tests/test_kline_workspace_js.py`: verify news/macro toggles and diagnostics rendering.
- Modify `src/kline/chart/types.ts` and `src/kline/chart/CandlestickChart.tsx`: include `news` category, confidence/impact-based particle rendering, and tooltip metadata.

## Task 1: Event Taxonomy, Scoring, And Filtering

**Files:**
- Create: `src/kline/event_filter.py`
- Create: `tests/test_kline_event_filter.py`

- [ ] **Step 1: Write failing tests for scored metadata and eligibility**

Create `tests/test_kline_event_filter.py` with:

```python
from __future__ import annotations

import pandas as pd


def test_score_event_metadata_marks_official_clinical_event_backtest_eligible():
    from src.kline.event_filter import enrich_event_metadata

    event = enrich_event_metadata(
        {
            "ticker": "MRNA",
            "date": "2026-04-20",
            "type": "trial_results_posted",
            "source": "clinicaltrials",
            "priority": 1,
            "sentiment": "positive",
            "source_ids": ["NCT00000001"],
            "metadata": {},
        }
    )

    assert event["category"] == "clinical"
    assert event["metadata"]["source_tier"] == "official"
    assert event["metadata"]["confidence_score"] >= 0.7
    assert event["metadata"]["impact_score"] >= 0.5
    assert event["metadata"]["backtest_eligible"] is True
    assert event["metadata"]["dedupe_key"] == (
        "MRNA|clinicaltrials|trial_results_posted|NCT00000001|2026-04-20"
    )


def test_macro_event_is_visible_but_not_backtest_eligible_by_default():
    from src.kline.event_filter import enrich_event_metadata

    event = enrich_event_metadata(
        {
            "ticker": "MRNA",
            "date": "2026-04-20",
            "type": "macro_economic",
            "source": "gdelt",
            "priority": 3,
            "sentiment": "neutral",
            "source_url": "https://example.com/macro",
            "metadata": {},
        }
    )

    assert event["category"] == "macro"
    assert event["metadata"]["source_tier"] == "macro"
    assert event["metadata"]["confidence_score"] < 0.85
    assert event["metadata"]["backtest_eligible"] is False


def test_filter_backtest_events_returns_summary_and_only_eligible_rows():
    from src.kline.event_filter import filter_backtest_events

    rows = pd.DataFrame(
        [
            {
                "id": "eligible",
                "date": "2026-04-20",
                "type": "trial_results_posted",
                "source": "clinicaltrials",
                "metadata": '{"backtest_eligible": true, "confidence_score": 0.9}',
            },
            {
                "id": "excluded",
                "date": "2026-04-21",
                "type": "macro_economic",
                "source": "gdelt",
                "metadata": '{"backtest_eligible": false, "confidence_score": 0.4}',
            },
        ]
    )

    eligible, summary = filter_backtest_events(rows)

    assert eligible["id"].tolist() == ["eligible"]
    assert summary == {
        "input_events": 2,
        "eligible_events": 1,
        "excluded_events": 1,
        "min_confidence_score": 0.7,
    }
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
pytest tests/test_kline_event_filter.py -q
```

Expected: import failure for `src.kline.event_filter`.

- [ ] **Step 3: Implement the event filter module**

Create `src/kline/event_filter.py` with:

```python
"""Kline phase2 event taxonomy, scoring, and filtering helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pandas as pd


OFFICIAL_SOURCES = {"clinicaltrials", "openfda", "cassandra_report", "report"}
MARKET_NEWS_SOURCES = {"alphavantage", "alpha_vantage"}
MACRO_SOURCES = {"gdelt"}

CLINICAL_TYPES = {
    "trial_results_posted",
    "trial_primary_completion",
    "trial_completion",
    "trial_status_change",
    "trial_termination",
    "clinical_readout",
}
REGULATORY_TYPES = {"fda_approval", "fda_decision", "fda_label_update", "fda_recall", "regulatory_change", "safety_signal"}
CORPORATE_TYPES = {"partnership", "partnership_mna", "financing", "earnings_financing", "patent", "competitor"}
NEWS_TYPES = {"market_news", "analyst_news"}
MACRO_TYPES = {"macro_policy", "geopolitical", "trade_policy", "sanctions", "macro_economic"}

TYPE_BASE_IMPACT = {
    "trial_results_posted": 0.90,
    "trial_primary_completion": 0.70,
    "trial_completion": 0.55,
    "trial_status_change": 0.45,
    "trial_termination": 0.85,
    "clinical_readout": 0.75,
    "fda_approval": 0.95,
    "fda_decision": 0.90,
    "fda_label_update": 0.70,
    "fda_recall": 0.80,
    "regulatory_change": 0.65,
    "safety_signal": 0.75,
    "partnership_mna": 0.70,
    "earnings_financing": 0.55,
    "analyst_news": 0.45,
    "market_news": 0.40,
    "sanctions": 0.55,
    "trade_policy": 0.45,
    "geopolitical": 0.35,
    "macro_policy": 0.40,
    "macro_economic": 0.30,
}


def category_for_event(event_type: object, source: object = None) -> str:
    event_type_text = str(event_type or "").strip().lower()
    source_text = str(source or "").strip().lower()
    if event_type_text in CLINICAL_TYPES:
        return "clinical"
    if event_type_text in REGULATORY_TYPES:
        return "regulatory"
    if event_type_text in CORPORATE_TYPES:
        return "corporate"
    if event_type_text in NEWS_TYPES or source_text in MARKET_NEWS_SOURCES:
        return "news"
    if event_type_text in MACRO_TYPES or source_text in MACRO_SOURCES:
        return "macro"
    if source_text in {"report", "cassandra_report", "cassandra"}:
        return "report"
    return "clinical"


def source_tier(source: object) -> str:
    source_text = str(source or "").strip().lower()
    if source_text in OFFICIAL_SOURCES:
        return "official"
    if source_text in MARKET_NEWS_SOURCES:
        return "market_news"
    if source_text in MACRO_SOURCES:
        return "macro"
    return "other"


def decode_metadata(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def encode_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def stable_dedupe_key(event: dict[str, Any]) -> str:
    ticker = str(event.get("ticker") or "").strip().upper()
    source = str(event.get("source") or "").strip().lower()
    event_type = str(event.get("type") or "").strip().lower()
    date = str(event.get("date") or "").strip()
    source_ids = event.get("source_ids") or []
    if isinstance(source_ids, str):
        try:
            source_ids = json.loads(source_ids)
        except json.JSONDecodeError:
            source_ids = [source_ids]
    if isinstance(source_ids, (list, tuple)) and source_ids:
        source_key = str(source_ids[0])
    else:
        source_key = str(event.get("source_url") or event.get("catalyst") or event.get("title") or "")
        source_key = re.sub(r"\s+", " ", source_key.strip().lower())[:180]
        source_key = hashlib.sha1(source_key.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return "|".join([ticker, source, event_type, source_key, date])


def score_confidence(event: dict[str, Any], metadata: dict[str, Any]) -> float:
    tier = source_tier(event.get("source"))
    if tier == "official":
        base = 0.82
    elif tier == "market_news":
        base = 0.62
    elif tier == "macro":
        base = 0.42
    else:
        base = 0.50
    if event.get("source_ids"):
        base += 0.08
    if event.get("source_url"):
        base += 0.04
    if metadata.get("entity_match") in {"ticker", "alias", "sponsor", "drug"}:
        base += 0.08
    return round(max(0.0, min(1.0, base)), 3)


def score_impact(event: dict[str, Any]) -> float:
    event_type = str(event.get("type") or "").strip().lower()
    base = TYPE_BASE_IMPACT.get(event_type, 0.35)
    priority = _int_value(event.get("priority"), default=3)
    priority_boost = {1: 0.12, 2: 0.06, 3: 0.0, 4: -0.04, 5: -0.08}.get(priority, 0.0)
    return round(max(0.0, min(1.0, base + priority_boost)), 3)


def is_backtest_eligible(event: dict[str, Any], metadata: dict[str, Any]) -> bool:
    tier = metadata.get("source_tier") or source_tier(event.get("source"))
    confidence = float(metadata.get("confidence_score") or 0.0)
    impact = float(metadata.get("impact_score") or 0.0)
    if tier == "official":
        return confidence >= 0.70
    if tier == "market_news":
        return confidence >= 0.75 and impact >= 0.45
    if tier == "macro":
        return confidence >= 0.85 and impact >= 0.55
    return confidence >= 0.80 and impact >= 0.50


def enrich_event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(event)
    metadata = decode_metadata(enriched.get("metadata"))
    enriched["category"] = enriched.get("category") or category_for_event(enriched.get("type"), enriched.get("source"))
    metadata.setdefault("source_tier", source_tier(enriched.get("source")))
    metadata.setdefault("confidence_score", score_confidence(enriched, metadata))
    metadata.setdefault("impact_score", score_impact(enriched))
    metadata.setdefault("dedupe_key", stable_dedupe_key(enriched))
    metadata.setdefault("backtest_eligible", is_backtest_eligible(enriched, metadata))
    enriched["metadata"] = metadata
    return enriched


def filter_backtest_events(events_df: pd.DataFrame, min_confidence_score: float = 0.70) -> tuple[pd.DataFrame, dict[str, Any]]:
    if events_df.empty:
        return events_df.copy(), {
            "input_events": 0,
            "eligible_events": 0,
            "excluded_events": 0,
            "min_confidence_score": min_confidence_score,
        }

    rows = events_df.copy()
    metadata_rows = rows["metadata"].apply(decode_metadata) if "metadata" in rows.columns else pd.Series([{}] * len(rows))
    eligible_mask = metadata_rows.apply(
        lambda metadata: bool(metadata.get("backtest_eligible")) and float(metadata.get("confidence_score") or 0.0) >= min_confidence_score
    )
    eligible = rows[eligible_mask].reset_index(drop=True)
    summary = {
        "input_events": int(len(rows)),
        "eligible_events": int(len(eligible)),
        "excluded_events": int(len(rows) - len(eligible)),
        "min_confidence_score": min_confidence_score,
    }
    return eligible, summary


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 4: Run tests and verify green**

Run:

```powershell
pytest tests/test_kline_event_filter.py -q
```

Expected: all tests pass.

## Task 2: Alpha Vantage News Client

**Files:**
- Create: `src/tools/alpha_vantage_news_client.py`
- Create: `tests/test_alpha_vantage_news_client.py`

- [ ] **Step 1: Write failing Alpha Vantage tests**

Create `tests/test_alpha_vantage_news_client.py` with:

```python
from __future__ import annotations


def test_fetch_market_news_returns_disabled_status_without_api_key(monkeypatch):
    from src.tools.alpha_vantage_news_client import fetch_market_news_events

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    events, status = fetch_market_news_events("MRNA")

    assert events == []
    assert status["source"] == "alphavantage"
    assert status["status"] == "disabled"
    assert status["item_count"] == 0
    assert "ALPHA_VANTAGE_API_KEY" in status["message"]


def test_normalize_news_sentiment_feed_classifies_life_sciences_news():
    from src.tools.alpha_vantage_news_client import normalize_news_sentiment_feed

    payload = {
        "feed": [
            {
                "title": "Moderna announces Phase 3 vaccine data and partnership",
                "url": "https://example.com/mrna-news",
                "time_published": "20260420T130000",
                "summary": "The company announced positive Phase 3 data.",
                "source": "Example Wire",
                "overall_sentiment_score": "0.42",
                "overall_sentiment_label": "Bullish",
                "ticker_sentiment": [
                    {
                        "ticker": "MRNA",
                        "relevance_score": "0.91",
                        "ticker_sentiment_score": "0.36",
                        "ticker_sentiment_label": "Bullish",
                    }
                ],
                "topics": [{"topic": "Life Sciences", "relevance_score": "0.95"}],
            }
        ]
    }

    events = normalize_news_sentiment_feed(payload, requested_ticker="MRNA")

    assert len(events) == 1
    event = events[0]
    assert event["ticker"] == "MRNA"
    assert event["source"] == "alphavantage"
    assert event["type"] == "partnership_mna"
    assert event["category"] == "news"
    assert event["date"] == "2026-04-20"
    assert event["sentiment"] == "positive"
    assert event["source_url"] == "https://example.com/mrna-news"
    assert event["metadata"]["source_tier"] == "market_news"
    assert event["metadata"]["confidence_score"] >= 0.6
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
pytest tests/test_alpha_vantage_news_client.py -q
```

Expected: import failure for `src.tools.alpha_vantage_news_client`.

- [ ] **Step 3: Implement Alpha Vantage client**

Create `src/tools/alpha_vantage_news_client.py` with:

```python
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
    limit: int = 100,
    api_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        "tickers": ticker.upper(),
        "topics": DEFAULT_TOPICS,
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

    if isinstance(payload, dict) and (payload.get("Note") or payload.get("Information")):
        message = str(payload.get("Note") or payload.get("Information"))
        status = "rate_limited" if "frequency" in message.lower() or "rate" in message.lower() else "error"
        return [], {"source": "alphavantage", "status": status, "item_count": 0, "message": message}

    events = normalize_news_sentiment_feed(payload, requested_ticker=ticker)
    return events, {
        "source": "alphavantage",
        "status": "ready" if events else "empty",
        "item_count": len(events),
        "message": None,
    }


def normalize_news_sentiment_feed(payload: dict[str, Any], requested_ticker: str) -> list[dict[str, Any]]:
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
            "id": "av-" + hashlib.sha1(f"{ticker}|{url or title}|{date}".encode("utf-8", errors="ignore")).hexdigest()[:16],
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
    if any(token in body for token in ("merger", "acquisition", "m&a", "partnership", "collaboration", "license", "licensing", "deal")):
        return "partnership_mna"
    if any(token in body for token in ("earnings", "offering", "financing", "debt", "cash runway", "guidance")):
        return "earnings_financing"
    if any(token in body for token in ("analyst", "upgrade", "downgrade", "price target", "rating")):
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


def _status_for_exception(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "rate" in text or "too many requests" in text:
        return "rate_limited"
    return "error"
```

- [ ] **Step 4: Run Alpha Vantage tests**

Run:

```powershell
pytest tests/test_alpha_vantage_news_client.py -q
```

Expected: all tests pass.

## Task 3: ClinicalTrials Milestones And Event Ingestion Integration

**Files:**
- Modify: `src/tools/clinical_trials_client.py`
- Modify: `src/services/event_ingestion_service.py`
- Modify: `tests/test_event_ingestion_service.py`

- [ ] **Step 1: Add failing tests for milestone expansion and Alpha Vantage source status**

Append to `tests/test_event_ingestion_service.py`:

```python
def test_normalize_clinical_trial_milestone_events_expands_key_dates():
    from src.tools.clinical_trials_client import normalize_clinical_trial_milestone_events

    events = normalize_clinical_trial_milestone_events(
        [
            {
                "nct_id": "NCT00000001",
                "title": "A Phase 3 Study",
                "status": "COMPLETED",
                "sponsor": "ModernaTX, Inc.",
                "conditions": "Melanoma",
                "interventions": "mRNA-4157",
                "phase": "Phase 3",
                "has_results": True,
                "primary_completion_date": "2026-04-18",
                "completion_date": "2026-04-19",
                "results_first_posted": "2026-04-20",
                "last_update_posted": "2026-04-21",
            }
        ],
        requested_ticker="MRNA",
    )

    assert [event["type"] for event in events] == [
        "trial_results_posted",
        "trial_primary_completion",
        "trial_completion",
        "trial_status_change",
    ]
    assert all(event["ticker"] == "MRNA" for event in events)
    assert all(event["source_ids"] == ["NCT00000001"] for event in events)
    assert all(event["metadata"]["source_tier"] == "official" for event in events)


def test_ingestion_records_alphavantage_disabled_when_key_missing(monkeypatch):
    from src.backtest.events_db import init_db, init_fetch_log_table, _get_conn
    from src.services import event_ingestion_service

    init_db()
    init_fetch_log_table()

    conn = _get_conn()
    conn.execute("DELETE FROM biotech_events WHERE ticker = 'AVDISABLED'")
    conn.execute("DELETE FROM fetch_log WHERE ticker = 'AVDISABLED'")
    conn.commit()
    conn.close()

    monkeypatch.setattr(event_ingestion_service, "OpenFDAClient", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_ingestion_service, "search_trials", lambda *args, **kwargs: [])
    monkeypatch.setattr(event_ingestion_service, "fetch_biotech_macro_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        event_ingestion_service,
        "fetch_market_news_events",
        lambda ticker: (
            [],
            {
                "source": "alphavantage",
                "status": "disabled",
                "item_count": 0,
                "message": "ALPHA_VANTAGE_API_KEY is not set",
            },
        ),
    )

    class EmptyFDA:
        def collect(self, ticker, limit=20):
            return {"label": {"results": []}, "event": {"results": []}, "drugsfda": {"results": []}}

    monkeypatch.setattr(event_ingestion_service, "OpenFDAClient", lambda *args, **kwargs: EmptyFDA())

    event_ingestion_service.get_events_for_ticker("AVDISABLED", max_age_hours=0)
    rows = event_ingestion_service.get_source_statuses_for_ticker("AVDISABLED")
    by_source = {row["source"]: row for row in rows}

    assert by_source["alphavantage"]["status"] == "disabled"
    assert "ALPHA_VANTAGE_API_KEY" in by_source["alphavantage"]["message"]
```

- [ ] **Step 2: Run targeted tests and verify red**

Run:

```powershell
pytest tests/test_event_ingestion_service.py::test_normalize_clinical_trial_milestone_events_expands_key_dates tests/test_event_ingestion_service.py::test_ingestion_records_alphavantage_disabled_when_key_missing -q
```

Expected: first test fails because the milestone function is missing; second fails because ingestion has no Alpha Vantage source.

- [ ] **Step 3: Implement milestone expansion**

In `src/tools/clinical_trials_client.py`, add a new function after `normalize_biotech_events()`:

```python
def normalize_clinical_trial_milestone_events(
    trials: List[Dict[str, Any]],
    source: str = "clinicaltrials",
    requested_ticker: str | None = None,
) -> List[Dict[str, Any]]:
    """Expand ClinicalTrials records into phase2 milestone events."""
    from src.kline.event_filter import enrich_event_metadata

    events: List[Dict[str, Any]] = []
    for trial in trials:
        try:
            sponsor = _coerce_text(trial.get("sponsor"), "UNKNOWN")
            ticker = requested_ticker.strip().upper() if requested_ticker is not None else (sponsor.split()[0] if sponsor else "UNKNOWN")
            nct_id = trial.get("nct_id") or trial.get("nct_number")
            valid_nct_id = nct_id if nct_id and nct_id not in {"Unknown", "N/A"} else None
            title = _coerce_text(trial.get("title"), "Clinical Trial")
            phase = _coerce_text(trial.get("phase") or trial.get("phases"), "")
            status = _coerce_text(trial.get("status") or trial.get("study_status"), "")
            conditions = _coerce_text(trial.get("conditions"), "")
            interventions = _coerce_text(trial.get("interventions"), "")
            disease_area = conditions.split(",")[0] if conditions else ""
            source_url = trial.get("url") or trial.get("study_url")
            if not source_url and valid_nct_id:
                source_url = f"https://clinicaltrials.gov/study/{valid_nct_id}"

            milestone_specs = [
                ("trial_results_posted", trial.get("results_first_posted"), "Results posted"),
                ("trial_primary_completion", trial.get("primary_completion_date"), "Primary completion"),
                ("trial_completion", trial.get("completion_date"), "Study completion"),
                ("trial_status_change", trial.get("last_update_posted"), f"Status update: {status or 'Unknown'}"),
            ]
            if status.upper() in {"TERMINATED", "SUSPENDED", "WITHDRAWN"}:
                milestone_specs = [
                    ("trial_termination", trial.get("completion_date") or trial.get("last_update_posted"), f"Trial {status.lower()}"),
                    ("trial_status_change", trial.get("last_update_posted"), f"Status update: {status}"),
                ]

            seen: set[tuple[str, str]] = set()
            for event_type, raw_date, label in milestone_specs:
                date_str = _clinical_event_date(raw_date)
                if not date_str:
                    continue
                key = (event_type, date_str)
                if key in seen:
                    continue
                seen.add(key)

                sentiment = "negative" if event_type == "trial_termination" else ("positive" if event_type == "trial_results_posted" else "neutral")
                priority = 1 if event_type in {"trial_results_posted", "trial_termination"} else 2
                metadata = {
                    "phase": phase,
                    "status": status,
                    "has_results": _to_bool(trial.get("has_results")),
                    "interventions": interventions,
                    "entity_match": "sponsor",
                    "raw_type": event_type,
                }
                why_stopped = trial.get("why_stopped")
                if why_stopped and why_stopped not in {"Reason not provided", "N/A"}:
                    metadata["why_stopped"] = why_stopped
                event = {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ticker}|{valid_nct_id}|{event_type}|{date_str}")),
                    "date": date_str,
                    "type": event_type,
                    "category": "clinical",
                    "priority": priority,
                    "ticker": ticker,
                    "disease_area": disease_area,
                    "catalyst": f"{label}: {title}",
                    "title": f"{label}: {title}",
                    "summary": f"{label} for {title}",
                    "sentiment": sentiment,
                    "price_impact": None,
                    "source": source,
                    "source_entity": sponsor,
                    "source_url": source_url,
                    "source_ids": [valid_nct_id] if valid_nct_id else [],
                    "confidence": "high" if valid_nct_id else "medium",
                    "metadata": metadata,
                }
                events.append(enrich_event_metadata(event))
        except Exception as e:
            logger.error(f"Error normalizing clinical trial milestones {trial.get('nct_id')}: {e}")
            continue
    return events


def _clinical_event_date(value: object) -> str | None:
    if not value or value in {"Unknown", "N/A"}:
        return None
    try:
        if isinstance(value, str) and len(value) == 10:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Wire Alpha Vantage and milestone ClinicalTrials into ingestion**

In `src/services/event_ingestion_service.py`:

1. Change imports:

```python
from src.tools.clinical_trials_client import (
    search_trials,
    normalize_biotech_events as normalize_clinical_trials,
    normalize_clinical_trial_milestone_events,
)
from src.tools.alpha_vantage_news_client import fetch_market_news_events
```

2. Change the source list:

```python
sources = ["openfda", "clinicaltrials", "alphavantage", "gdelt"]
```

3. In the ClinicalTrials branch, prefer milestone events:

```python
events = normalize_clinical_trial_milestone_events(
    trials,
    source="clinicaltrials",
    requested_ticker=ticker,
)
```

4. Add an Alpha Vantage branch before GDELT:

```python
elif source == "alphavantage":
    events, source_status = fetch_market_news_events(ticker)
    item_count = len(events)
    if events:
        insert_events(events)
        logger.info(f"Inserted {item_count} Alpha Vantage news events for {ticker}")
    record_fetch_attempt(
        ticker,
        source,
        item_count,
        status=source_status.get("status"),
        message=source_status.get("message"),
    )
```

- [ ] **Step 5: Run event ingestion tests**

Run:

```powershell
pytest tests/test_event_ingestion_service.py -q
```

Expected: all event ingestion tests pass.

## Task 4: Backtest Eligibility, Attribution, And Baseline Diagnostics

**Files:**
- Create: `src/backtest/attribution.py`
- Modify: `src/backtest/signals.py`
- Modify: `src/backtest/runner.py`
- Modify: `tests/test_kline_backtest_runner.py`

- [ ] **Step 1: Write failing tests for phase2 diagnostics**

Append to `tests/test_kline_backtest_runner.py`:

```python
def test_run_kline_backtest_returns_phase2_event_diagnostics(tmp_path, monkeypatch):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {"date": "2026-04-20", "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0, "volume": 1000},
            {"date": "2026-04-21", "open": 103.0, "high": 106.0, "low": 101.0, "close": 105.0, "volume": 1100},
            {"date": "2026-04-22", "open": 105.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 1200},
        ]
    )
    events = pd.DataFrame(
        [
            {
                "id": "evt-eligible",
                "date": "2026-04-20",
                "type": "trial_results_posted",
                "priority": 1,
                "sentiment": "positive",
                "source": "clinicaltrials",
                "metadata": '{"backtest_eligible": true, "confidence_score": 0.9, "impact_score": 0.8, "source_tier": "official"}',
            },
            {
                "id": "evt-excluded",
                "date": "2026-04-21",
                "type": "macro_economic",
                "priority": 3,
                "sentiment": "neutral",
                "source": "gdelt",
                "metadata": '{"backtest_eligible": false, "confidence_score": 0.4, "impact_score": 0.2, "source_tier": "macro"}',
            },
        ]
    )

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "get_events", lambda *args, **kwargs: events)

    payload = runner.run_kline_backtest(
        ticker="MRNA",
        start_date="2026-04-20",
        end_date="2026-04-22",
    )

    assert payload["event_filter"] == {
        "input_events": 2,
        "eligible_events": 1,
        "excluded_events": 1,
        "min_confidence_score": 0.7,
    }
    assert payload["event_attribution"]["by_source"][0]["source"] == "clinicaltrials"
    assert payload["signal_summary"]["active_signal_days"] >= 1
    assert payload["baseline"]["buy_hold_return"] == 0.06
    assert "strategy_return" in payload["baseline"]
```

- [ ] **Step 2: Run test and verify red**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_run_kline_backtest_returns_phase2_event_diagnostics -q
```

Expected: fails because diagnostics fields are missing.

- [ ] **Step 3: Implement attribution helpers**

Create `src/backtest/attribution.py` with:

```python
"""Backtest attribution diagnostics for phase2 Kline events."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.kline.event_filter import decode_metadata


def summarize_events(events: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    if events.empty:
        return {"by_source": [], "by_category": [], "by_type": []}
    rows = events.copy()
    if "category" not in rows.columns:
        rows["category"] = rows.apply(_category_from_row, axis=1)
    return {
        "by_source": _count_rows(rows, "source"),
        "by_category": _count_rows(rows, "category"),
        "by_type": _count_rows(rows, "type"),
    }


def summarize_signals(signals: pd.DataFrame) -> dict[str, Any]:
    if signals.empty:
        return {
            "active_signal_days": 0,
            "long_signal_days": 0,
            "short_signal_days": 0,
            "mean_signal_strength": 0.0,
        }
    active = signals[signals["signal"] != 0]
    return {
        "active_signal_days": int(len(active)),
        "long_signal_days": int((signals["signal"] > 0).sum()),
        "short_signal_days": int((signals["signal"] < 0).sum()),
        "mean_signal_strength": round(float(active["signal_strength"].mean()), 6) if not active.empty else 0.0,
    }


def compute_baseline(price_window: pd.DataFrame, results: pd.DataFrame) -> dict[str, float | None]:
    if price_window.empty or len(price_window) < 2 or results.empty:
        return {"buy_hold_return": None, "strategy_return": None, "excess_return": None}
    first_open = float(price_window.iloc[0]["open"])
    last_close = float(price_window.iloc[-1]["close"])
    buy_hold = last_close / first_open - 1 if first_open else 0.0
    strategy = float(results.iloc[-1]["equity"]) / float(results.iloc[0]["equity"]) - 1
    return {
        "buy_hold_return": round(buy_hold, 6),
        "strategy_return": round(strategy, 6),
        "excess_return": round(strategy - buy_hold, 6),
    }


def _count_rows(rows: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if column not in rows.columns:
        return []
    grouped = rows.groupby(column).size().reset_index(name="count")
    return [
        {column: str(getattr(row, column)), "count": int(row.count)}
        for row in grouped.itertuples(index=False)
    ]


def _category_from_row(row: pd.Series) -> str:
    metadata = decode_metadata(row.get("metadata"))
    if metadata.get("source_tier") == "market_news":
        return "news"
    if metadata.get("source_tier") == "macro":
        return "macro"
    return "clinical"
```

- [ ] **Step 4: Update signal generation to respect eligibility metadata**

In `src/backtest/signals.py`, import `decode_metadata` and expand scoring:

```python
from src.kline.event_filter import decode_metadata
```

Replace `score_event()` with:

```python
def score_event(event: dict) -> float:
    """Score a single event using phase2 metadata when available."""
    metadata = decode_metadata(event.get("metadata"))
    if metadata and metadata.get("backtest_eligible") is False:
        return 0.0
    type_w = EVENT_SCORE.get(event.get("type", ""), 0.3)
    impact_score = metadata.get("impact_score")
    confidence_score = metadata.get("confidence_score")
    if impact_score is not None:
        type_w = max(type_w, float(impact_score))
    prio_w = PRIORITY_WEIGHT.get(event.get("priority", 3), 0.3)
    sent_d = SENTIMENT_DIRECTION.get(event.get("sentiment", "neutral"), 0.0)
    confidence_w = float(confidence_score) if confidence_score is not None else 1.0
    return type_w * prio_w * sent_d * confidence_w
```

Extend `EVENT_SCORE` with the phase2 taxonomy names:

```python
"trial_results_posted": 0.95,
"trial_primary_completion": 0.7,
"trial_completion": 0.55,
"trial_status_change": 0.45,
"trial_termination": 0.9,
"fda_approval": 1.0,
"fda_label_update": 0.7,
"fda_recall": 0.8,
"safety_signal": 0.75,
"market_news": 0.4,
"analyst_news": 0.35,
"partnership_mna": 0.65,
"earnings_financing": 0.45,
"macro_policy": 0.3,
```

Extend `PRIORITY_WEIGHT`:

```python
PRIORITY_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.3, 4: 0.2, 5: 0.15}
```

- [ ] **Step 5: Update runner diagnostics**

In `src/backtest/runner.py`, import helpers:

```python
from src.backtest.attribution import compute_baseline, summarize_events, summarize_signals
from src.kline.event_filter import filter_backtest_events
```

After loading `events`, add:

```python
eligible_events, event_filter = filter_backtest_events(events)
```

Pass `eligible_events` to `generate_signals()` and `compute_event_car()`:

```python
signals = generate_signals(price_window, eligible_events, report_confidence=report_confidence)
car_df = compute_event_car(price_window, eligible_events)
```

In the payload, add:

```python
"event_filter": event_filter,
"event_attribution": summarize_events(eligible_events),
"signal_summary": summarize_signals(signals),
"baseline": compute_baseline(price_window, results),
```

- [ ] **Step 6: Run backtest tests**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py -q
```

Expected: all backtest runner tests pass.

## Task 5: Workspace Event Layers And Static UI

**Files:**
- Modify: `src/kline/models.py`
- Modify: `src/kline/workspace_service.py`
- Modify: `src/kline/providers/catalyst_provider.py`
- Modify: `static/kline/workspace.js`
- Modify: `tests/test_kline_workspace_service.py`
- Modify: `tests/test_kline_workspace_js.py`

- [ ] **Step 1: Write failing workspace service test for phase2 layers**

Append to `tests/test_kline_workspace_service.py`:

```python
def test_workspace_payload_splits_catalyst_news_and_macro_layers():
    contracts = _contracts()

    class MixedEventProvider:
        def load(self, ticker: str):
            return [
                contracts.KlineEvent(
                    id="clinical-1",
                    ticker=ticker,
                    date="2026-04-20",
                    type="trial_results_posted",
                    category="clinical",
                    title="Results posted",
                    summary="Results posted",
                    sentiment="positive",
                    priority=1,
                    confidence="high",
                    source="clinicaltrials",
                ),
                contracts.KlineEvent(
                    id="news-1",
                    ticker=ticker,
                    date="2026-04-21",
                    type="market_news",
                    category="news",
                    title="Market news",
                    summary="Market news",
                    sentiment="positive",
                    priority=3,
                    confidence="medium",
                    source="alphavantage",
                ),
                contracts.KlineEvent(
                    id="macro-1",
                    ticker=ticker,
                    date="2026-04-22",
                    type="macro_economic",
                    category="macro",
                    title="Macro context",
                    summary="Macro context",
                    sentiment="neutral",
                    priority=3,
                    confidence="low",
                    source="gdelt",
                ),
            ], []

    service = contracts.KlineWorkspaceService(
        resolver=contracts.TickerResolver(),
        ohlc_provider=FakeOHLCProvider(
            contracts.KlineDataStatus,
            contracts.KlinePriceSeries,
        ),
        catalyst_provider=MixedEventProvider(),
        backtest_provider=FakeBacktestProvider(),
    )

    payload = service.build_workspace("MRNA").to_dict()
    layers = {layer["kind"]: layer for layer in payload["layers"]}

    assert [layer["kind"] for layer in payload["layers"]] == [
        "candles",
        "catalysts",
        "news",
        "macro",
        "backtest",
    ]
    assert [event["id"] for event in layers["catalysts"]["points"]] == ["clinical-1"]
    assert [event["id"] for event in layers["news"]["points"]] == ["news-1"]
    assert [event["id"] for event in layers["macro"]["points"]] == ["macro-1"]
    assert {"id": "news", "enabled": True, "phase": 2, "label": "News"} in payload["capabilities"]
```

- [ ] **Step 2: Run workspace service test and verify red**

Run:

```powershell
pytest tests/test_kline_workspace_service.py::test_workspace_payload_splits_catalyst_news_and_macro_layers -q
```

Expected: fails because layers are not split and news capability is disabled.

- [ ] **Step 3: Enable phase2 capabilities**

In `src/kline/models.py`, change `disabled_future_capabilities()` to return enabled news/macro and disabled phase3 items:

```python
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
```

- [ ] **Step 4: Split workspace event layers**

In `src/kline/workspace_service.py`, replace the `layers` construction with:

```python
hard_events = [event for event in catalysts if event.category not in {"news", "macro"}]
news_events = [event for event in catalysts if event.category == "news"]
macro_events = [event for event in catalysts if event.category == "macro"]
layers = [
    _candles_layer(price),
    _events_layer("catalysts", "catalysts", "Catalysts", hard_events, True),
    _events_layer("news", "news", "News", news_events, True),
    _events_layer("macro", "macro", "Macro", macro_events, False),
    _backtest_layer(last_backtest),
]
```

Add helper:

```python
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
```

Keep `_catalysts_layer()` only if existing tests still reference it; otherwise remove it after updating call sites.

- [ ] **Step 5: Improve provider metadata projection**

In `src/kline/providers/catalyst_provider.py`, in `_normalize_event()`:

1. Let metadata category override heuristic when valid:

```python
metadata_category = _optional_string(metadata.get("category"))
category = metadata_category or _category_for(raw)
```

2. Set `impact_score` from metadata when top-level impact is missing:

```python
impact_score=_impact_score(raw) or metadata.get("impact_score"),
```

3. Include category in the `KlineEvent` constructor:

```python
category=category,
```

- [ ] **Step 6: Write failing workspace JS tests for generic layer toggles and diagnostics**

Append to `tests/test_kline_workspace_js.py`:

```python
def test_workspace_js_combines_active_event_layers_and_toggles_news_layer():
    result = _run_workspace_script(
        r"""
        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{ id: 'clinical-1', date: '2026-04-20', type: 'trial_results_posted', category: 'clinical', priority: 1, sentiment: 'positive' }]
          }, {
            kind: 'news',
            label: 'News',
            visible_by_default: true,
            points: [{ id: 'news-1', date: '2026-04-20', type: 'market_news', category: 'news', priority: 3, sentiment: 'positive' }]
          }, {
            kind: 'macro',
            label: 'Macro',
            visible_by_default: false,
            points: [{ id: 'macro-1', date: '2026-04-20', type: 'macro_economic', category: 'macro', priority: 3, sentiment: 'neutral' }]
          }]
        }));
        runWorkspace();

        let latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.events.map((event) => event.id).join(',') !== 'clinical-1,news-1') {
          throw new Error('expected active catalyst and news events, got ' + latestConfig.events.map((event) => event.id).join(','));
        }

        const layerBar = document.getElementById('layer-bar');
        const newsButton = layerBar.children.find((child) => child.dataset.layerKind === 'news');
        newsButton.dispatchEvent({ type: 'click' });

        latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.events.map((event) => event.id).join(',') !== 'clinical-1') {
          throw new Error('news toggle did not remove news events');
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_renders_phase2_diagnostics():
    result = _run_workspace_script(
        r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'phase2-run',
            metrics: { sharpe: 1.1 },
            equity_curve: [],
            signals: [],
            trades: [],
            event_filter: { input_events: 4, eligible_events: 2, excluded_events: 2, min_confidence_score: 0.7 },
            signal_summary: { active_signal_days: 1, long_signal_days: 1, short_signal_days: 0, mean_signal_strength: 0.25 },
            baseline: { buy_hold_return: 0.1, strategy_return: 0.03, excess_return: -0.07 }
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const text = document.getElementById('backtest-results').textContent;
        if (!text.includes('eligible_events') || !text.includes('buy_hold_return')) {
          throw new Error('phase2 diagnostics were not rendered: ' + text);
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout
```

- [ ] **Step 7: Update workspace.js for event layers and diagnostics**

In `static/kline/workspace.js`:

1. Add:

```javascript
  function eventLayers(workspace) {
    return (workspace.layers || []).filter(function (layer) {
      return ["catalysts", "news", "macro"].indexOf(layer.kind) !== -1;
    });
  }

  function activeEvents(workspace, state) {
    return eventLayers(workspace).flatMap(function (layer) {
      return state.visibleEventLayers[layer.kind] ? (layer.points || []) : [];
    });
  }
```

2. In `renderChart()`, replace the events field with:

```javascript
events: activeEvents(workspace, state),
```

3. In `init()`, replace `showCatalysts` with:

```javascript
visibleEventLayers: Object.fromEntries(eventLayers(workspace).map(function (layer) {
  return [layer.kind, layer.visible_by_default !== false];
})),
```

4. In `renderLayerBar()`, treat all event layers generically:

```javascript
var isEventLayer = ["catalysts", "news", "macro"].indexOf(layer.kind) !== -1;
var isActive = isEventLayer
  ? state.visibleEventLayers[layer.kind]
  : isBacktest
    ? state.showBacktest && hasBacktestOverlays(state)
    : layer.visible_by_default !== false;
if (isEventLayer) {
  button.addEventListener("click", function () {
    state.visibleEventLayers[layer.kind] = !state.visibleEventLayers[layer.kind];
    renderLayerBar(workspace, state);
    renderChart(workspace, state);
  });
}
```

5. Add diagnostics rendering:

```javascript
  function renderBacktestDiagnostics(node, body) {
    ["event_filter", "signal_summary", "baseline"].forEach(function (key) {
      if (!body[key]) {
        return;
      }
      var heading = makeElement("h3", { className: "panel-heading", text: key });
      node.appendChild(heading);
      renderMetrics(node, body[key]);
    });
  }
```

6. After `renderMetrics(results, body.metrics || {});`, call:

```javascript
renderBacktestDiagnostics(results, body);
```

- [ ] **Step 8: Run workspace tests**

Run:

```powershell
pytest tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py -q
```

Expected: all tests pass.

## Task 6: Chart Particle Metadata Polish And Bundle Build

**Files:**
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Generated by build: `static/vendor/pokie-chart.umd.js`
- Generated by build: `static/vendor/pokie-chart.css`

- [ ] **Step 1: Update chart types**

In `src/kline/chart/types.ts`, include `news`:

```typescript
category?: 'clinical' | 'regulatory' | 'corporate' | 'news' | 'macro' | 'report';
```

Add optional metadata projection:

```typescript
backtest_eligible?: boolean;
confidence_score?: number;
```

- [ ] **Step 2: Update chart category colors and particle opacity**

In `src/kline/chart/CandlestickChart.tsx`, add news color:

```typescript
news: '#38bdf8',
```

Replace `getEventAlpha()` with:

```typescript
function getEventAlpha(priority: number, confidenceScore?: number): number {
  if (typeof confidenceScore === 'number') {
    return Math.max(0.25, Math.min(1, confidenceScore));
  }
  return priority === 1 ? 0.8 : priority === 2 ? 0.6 : 0.4;
}
```

When placing events, derive metadata scores:

```typescript
const confidenceScore = typeof evt.confidence_score === 'number'
  ? evt.confidence_score
  : typeof evt.metadata?.confidence_score === 'number'
    ? evt.metadata.confidence_score
    : undefined;
const impactScore = typeof evt.impact_score === 'number'
  ? evt.impact_score
  : typeof evt.metadata?.impact_score === 'number'
    ? evt.metadata.impact_score
    : undefined;
```

Use `impactScore` for radius and `confidenceScore` for alpha.

- [ ] **Step 3: Update tooltip metadata**

In the tooltip block, append confidence and eligibility:

```typescript
const confidenceScore = typeof hit.metadata?.confidence_score === 'number' ? hit.metadata.confidence_score : undefined;
const backtestEligible = hit.metadata?.backtest_eligible === true ? 'eligible' : 'visual only';
const confidence = document.createElement('span');
confidence.className = 'pt-ret';
confidence.textContent = confidenceScore !== undefined ? `Confidence: ${confidenceScore.toFixed(2)}` : backtestEligible;
meta.append(type, impact, confidence);
```

- [ ] **Step 4: Build the chart bundle**

Run:

```powershell
npm --prefix src/kline run build
```

Expected: Vite/TypeScript build exits 0 and refreshes `static/vendor/pokie-chart.umd.js`.

## Task 7: Full Verification

**Files:**
- Verify all files touched above.

- [ ] **Step 1: Run focused backend/static tests**

Run:

```powershell
pytest tests/test_kline_event_filter.py tests/test_alpha_vantage_news_client.py tests/test_event_ingestion_service.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp_kline_phase2_final
```

Expected: all selected tests pass.

- [ ] **Step 2: Run chart build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected: exit code 0.

- [ ] **Step 3: Inspect final diff**

Run:

```powershell
git diff -- src/kline src/tools/alpha_vantage_news_client.py src/tools/clinical_trials_client.py src/services/event_ingestion_service.py src/backtest tests static/kline static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css docs/superpowers/specs/2026-04-29-kline-phase2-multisource-events-design.md docs/superpowers/plans/2026-04-29-kline-phase2-multisource-events-implementation.md
```

Expected: diff contains only phase2 Kline event, backtest, workspace, test, spec, and plan changes.
