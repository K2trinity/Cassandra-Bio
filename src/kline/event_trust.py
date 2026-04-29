"""Trust and provenance helpers for Kline event data."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import datetime, timezone
from typing import Any

TRUSTED_SCHEMA_VERSION = 2
TRUSTED_STATUSES = {"trusted"}
TRUSTED_OWNERSHIP_STATUSES = {"owned", "market_relevant", "macro_context"}
BACKTEST_TRUSTED_OWNERSHIP_STATUSES = {
    "owned",
    "market_relevant",
    "macro_context",
}


def decode_metadata(value: object) -> dict[str, Any]:
    """Decode metadata from dict or JSON string, returning {} for bad data."""
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
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def build_source_run_id(
    ticker: object,
    source: object,
    now: datetime | None = None,
) -> str:
    """Build a unique run identifier for a source/ticker fetch."""
    timestamp = _utc_datetime(now).strftime("%Y%m%dT%H%M%SZ")
    source_key = str(source or "unknown").strip().lower() or "unknown"
    ticker_key = str(ticker or "UNKNOWN").strip().upper() or "UNKNOWN"
    return f"{source_key}:{ticker_key}:{timestamp}:{secrets.token_hex(4)}"


def build_query_hash(
    source: object,
    ticker: object,
    params: dict[str, Any] | None = None,
) -> str:
    """Build a stable 16-character hash for source query parameters."""
    payload = {
        "params": params or {},
        "source": str(source or "").strip().lower(),
        "ticker": str(ticker or "").strip().upper(),
    }
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def apply_event_trust(
    event: dict[str, Any],
    *,
    ticker: object,
    source: object,
    source_run_id: str,
    query_hash: str,
    company_identity: str,
    ownership_status: str,
    trust_status: str = "trusted",
    quarantine_reason: str | None = None,
) -> dict[str, Any]:
    """Return an event decorated with trust and provenance fields."""
    trusted_event = dict(event)
    trusted_event.setdefault("source", source)
    trust_fields = {
        "ticker_scope": str(ticker or "").strip().upper(),
        "source_run_id": source_run_id,
        "query_hash": query_hash,
        "company_identity": company_identity,
        "ownership_status": ownership_status,
        "trust_status": trust_status,
        "schema_version": TRUSTED_SCHEMA_VERSION,
        "quarantine_reason": quarantine_reason,
    }
    trusted_event.update(trust_fields)

    metadata = decode_metadata(trusted_event.get("metadata"))
    metadata.update(trust_fields)
    trusted_event["metadata"] = metadata
    return trusted_event


def is_metadata_backtest_eligible(value: object) -> bool:
    """Return true only for explicit boolean True metadata.backtest_eligible."""
    metadata = decode_metadata(value)
    return metadata.get("backtest_eligible") is True


def _utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
