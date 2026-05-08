from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


def record_provider_fetch(
    *,
    provider: str,
    endpoint: str,
    request_hash: str,
    status: str,
    retry_count: int = 0,
    message: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Record an offline provider fetch attempt in the research DuckDB catalog."""
    normalized_provider = _require_text(provider, "provider").lower()
    normalized_endpoint = _require_text(endpoint, "endpoint")
    normalized_request_hash = _require_text(request_hash, "request_hash")
    normalized_status = _require_text(status, "status")
    normalized_retry_count = int(retry_count)
    if normalized_retry_count < 0:
        raise ValueError("retry_count must be non-negative")

    metadata_json = json.dumps(
        dict(metadata or {}),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    fetch_id = build_provider_fetch_id(
        provider=normalized_provider,
        endpoint=normalized_endpoint,
        request_hash=normalized_request_hash,
    )

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            "DELETE FROM provider_fetch_log WHERE fetch_id = ?",
            [fetch_id],
        )
        conn.execute(
            """
            INSERT INTO provider_fetch_log (
                fetch_id,
                provider,
                endpoint,
                request_hash,
                status,
                retry_count,
                message,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                fetch_id,
                normalized_provider,
                normalized_endpoint,
                normalized_request_hash,
                normalized_status,
                normalized_retry_count,
                str(message) if message is not None else None,
                metadata_json,
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return fetch_id


def build_provider_fetch_id(
    *,
    provider: str,
    endpoint: str,
    request_hash: str,
) -> str:
    payload = {
        "endpoint": _require_text(endpoint, "endpoint"),
        "provider": _require_text(provider, "provider").lower(),
        "request_hash": _require_text(request_hash, "request_hash"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"fetch_{digest}"


def _require_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text

