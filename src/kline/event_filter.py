"""Kline phase2 event taxonomy, scoring, and filtering helpers."""

from __future__ import annotations

import hashlib
import json
import math
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
REGULATORY_TYPES = {
    "fda_approval",
    "fda_decision",
    "fda_label_update",
    "fda_recall",
    "regulatory_change",
    "safety_signal",
}
CORPORATE_TYPES = {
    "partnership",
    "partnership_mna",
    "financing",
    "earnings_financing",
    "patent",
    "competitor",
}
NEWS_TYPES = {"market_news", "analyst_news"}
MACRO_TYPES = {
    "macro_policy",
    "geopolitical",
    "trade_policy",
    "sanctions",
    "macro_economic",
    "macro",
}

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
    "macro": 0.30,
}


def category_for_event(event_type: object, source: object = None) -> str:
    """Return the display/analytics category for an event."""
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
    """Return the evidence tier implied by the source."""
    source_text = str(source or "").strip().lower()
    if source_text in OFFICIAL_SOURCES:
        return "official"
    if source_text in MARKET_NEWS_SOURCES:
        return "market_news"
    if source_text in MACRO_SOURCES:
        return "macro"
    return "other"


def source_kind_for_event(category: str, source: object = None) -> str:
    """Return a durable source-kind label for metadata consumers."""
    source_text = str(source or "").strip().lower()
    if source_text in MARKET_NEWS_SOURCES:
        return "news"
    if source_text in MACRO_SOURCES:
        return "macro"
    if source_text == "openfda":
        return "regulatory"
    if source_text == "clinicaltrials":
        return "clinical"
    if category in {"clinical", "regulatory", "corporate", "news", "macro", "report"}:
        return category
    return "other"


def decode_metadata(value: object) -> dict[str, Any]:
    """Decode metadata stored as dict or JSON string."""
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, float) and math.isnan(value):
        return {}
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def encode_metadata(metadata: dict[str, Any]) -> str:
    """Encode metadata consistently for storage."""
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def stable_dedupe_key(event: dict[str, Any]) -> str:
    """Build a stable cross-run dedupe key for semantically identical events."""
    ticker = str(event.get("ticker") or "").strip().upper()
    source = str(event.get("source") or "").strip().lower()
    event_type = str(event.get("type") or "").strip().lower()
    date = str(event.get("date") or "").strip()
    source_ids = event.get("source_ids") or []
    if isinstance(source_ids, str):
        try:
            decoded = json.loads(source_ids)
            source_ids = decoded if isinstance(decoded, list) else [source_ids]
        except json.JSONDecodeError:
            source_ids = [source_ids]
    if isinstance(source_ids, (list, tuple)) and source_ids:
        source_key = str(source_ids[0])
    else:
        source_key = str(
            event.get("source_url") or event.get("catalyst") or event.get("title") or ""
        )
        source_key = re.sub(r"\s+", " ", source_key.strip().lower())[:180]
        source_key = hashlib.sha1(
            source_key.encode("utf-8", errors="ignore")
        ).hexdigest()[:16]
    return "|".join([ticker, source, event_type, source_key, date])


def score_confidence(event: dict[str, Any], metadata: dict[str, Any]) -> float:
    """Score event confidence from source tier and source-specific evidence."""
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
    """Score likely market impact from taxonomy and priority."""
    event_type = str(event.get("type") or "").strip().lower()
    base = TYPE_BASE_IMPACT.get(event_type, 0.35)
    priority = _int_value(event.get("priority"), default=3)
    priority_boost = {1: 0.12, 2: 0.06, 3: 0.0, 4: -0.04, 5: -0.08}.get(
        priority,
        0.0,
    )
    return round(max(0.0, min(1.0, base + priority_boost)), 3)


def is_backtest_eligible(event: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Return whether an event should be considered by backtests by default."""
    tier = metadata.get("source_tier") or source_tier(event.get("source"))
    confidence = _float_value(metadata.get("confidence_score"), 0.0)
    impact = _float_value(metadata.get("impact_score"), 0.0)
    if tier == "official":
        return confidence >= 0.70
    if tier == "market_news":
        return confidence >= 0.75 and impact >= 0.45
    if tier == "macro":
        return confidence >= 0.85 and impact >= 0.55
    return confidence >= 0.80 and impact >= 0.50


def enrich_event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Return an event with phase2 taxonomy, scoring, and filtering metadata."""
    enriched = dict(event)
    metadata = decode_metadata(enriched.get("metadata"))
    category = str(
        enriched.get("category")
        or category_for_event(enriched.get("type"), enriched.get("source"))
    )
    enriched["category"] = category
    metadata.setdefault("category", category)
    metadata.setdefault(
        "source_kind", source_kind_for_event(category, enriched.get("source"))
    )
    metadata.setdefault("source_tier", source_tier(enriched.get("source")))
    metadata.setdefault("confidence_score", score_confidence(enriched, metadata))
    metadata.setdefault("impact_score", score_impact(enriched))
    metadata.setdefault("dedupe_key", stable_dedupe_key(enriched))
    metadata.setdefault("backtest_eligible", is_backtest_eligible(enriched, metadata))
    enriched["metadata"] = metadata
    return enriched


def filter_backtest_events(
    events_df: pd.DataFrame,
    min_confidence_score: float = 0.70,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter event rows to those eligible for backtests and return diagnostics."""
    if events_df.empty:
        return events_df.copy(), {
            "input_events": 0,
            "eligible_events": 0,
            "excluded_events": 0,
            "min_confidence_score": min_confidence_score,
        }

    rows = _enrich_event_rows(events_df.copy())
    metadata_rows = rows["metadata"].apply(decode_metadata)
    eligible_mask = metadata_rows.apply(
        lambda metadata: _bool_value(metadata.get("backtest_eligible"))
        and _float_value(metadata.get("confidence_score"), 0.0) >= min_confidence_score
    )
    eligible = rows[eligible_mask].reset_index(drop=True)
    summary = {
        "input_events": int(len(rows)),
        "eligible_events": int(len(eligible)),
        "excluded_events": int(len(rows) - len(eligible)),
        "min_confidence_score": min_confidence_score,
    }
    return eligible, summary


def _enrich_event_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Return rows with phase2 metadata filled when legacy rows lack it."""
    existing_columns = rows.columns.tolist()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        event = row.to_dict()
        metadata = decode_metadata(event.get("metadata"))
        if _needs_phase2_metadata(metadata):
            event["metadata"] = metadata
            event = enrich_event_metadata(event)
        else:
            event["metadata"] = metadata
        records.append(event)

    return pd.DataFrame(
        records, columns=existing_columns + _extra_columns(records, existing_columns)
    )


def _needs_phase2_metadata(metadata: dict[str, Any]) -> bool:
    required_keys = {
        "source_tier",
        "confidence_score",
        "impact_score",
        "backtest_eligible",
    }
    return not required_keys.issubset(metadata)


def _extra_columns(
    records: list[dict[str, Any]], existing_columns: list[str]
) -> list[str]:
    seen = set(existing_columns)
    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _float_value(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
