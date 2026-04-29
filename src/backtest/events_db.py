# src/backtest/events_db.py
"""SQLite event store for biotech catalysts."""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from src.kline.event_trust import (
    BACKTEST_TRUSTED_OWNERSHIP_STATUSES,
    TRUSTED_OWNERSHIP_STATUSES,
    TRUSTED_SCHEMA_VERSION,
    TRUSTED_STATUSES,
    decode_metadata,
    is_metadata_backtest_eligible,
)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "events.db"


EVENT_COLUMN_DEFINITIONS = {
    "source_entity": "TEXT",
    "source_url": "TEXT",
    "source_ids": "TEXT",
    "confidence": "TEXT DEFAULT 'medium'",
    "metadata": "TEXT",
    "ticker_scope": "TEXT",
    "source_run_id": "TEXT",
    "query_hash": "TEXT",
    "company_identity": "TEXT",
    "ownership_status": "TEXT DEFAULT 'unknown'",
    "trust_status": "TEXT DEFAULT 'legacy_untrusted'",
    "schema_version": "INTEGER DEFAULT 1",
    "quarantine_reason": "TEXT",
}

EVENT_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS biotech_events (
        id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 3,
        ticker TEXT NOT NULL,
        disease_area TEXT,
        catalyst TEXT,
        sentiment TEXT DEFAULT 'neutral',
        price_impact REAL,
        source TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )
"""

FETCH_LOG_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS fetch_log (
        ticker TEXT NOT NULL,
        source TEXT NOT NULL,
        last_fetch_at TEXT NOT NULL,
        item_count INTEGER DEFAULT 0,
        status TEXT,
        message TEXT,
        PRIMARY KEY (ticker, source)
    )
"""

FETCH_LOG_COLUMN_DEFINITIONS = {
    "status": "TEXT",
    "message": "TEXT",
}


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create events table if not exists."""
    conn = _get_conn()
    _ensure_event_table(conn)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ticker_date
        ON biotech_events(ticker, date)
    """)
    conn.commit()
    conn.close()


def _ensure_event_table(conn: sqlite3.Connection) -> None:
    """Create or migrate the biotech event table without dropping existing data."""
    conn.execute(EVENT_TABLE_SQL)
    _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add optional event attribution columns to older databases."""
    existing_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(biotech_events)").fetchall()
    }
    for column_name, column_definition in EVENT_COLUMN_DEFINITIONS.items():
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE biotech_events ADD COLUMN {column_name} {column_definition}")


def _serialize_json_field(value: object, default: object) -> str:
    if value is None:
        value = default
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _serialize_event(event: dict) -> dict:
    """Return an insert-ready event with structured fields serialized."""
    serialized = dict(event)
    serialized.setdefault("priority", 3)
    serialized.setdefault("sentiment", "neutral")
    serialized.setdefault("price_impact", None)
    serialized.setdefault("source_entity", None)
    serialized.setdefault("source_url", None)
    serialized.setdefault("confidence", "medium")
    if not serialized.get("ticker_scope"):
        serialized["ticker_scope"] = serialized.get("ticker")
    serialized.setdefault("source_run_id", None)
    serialized.setdefault("query_hash", None)
    serialized.setdefault("company_identity", None)
    if not serialized.get("ownership_status"):
        serialized["ownership_status"] = "unknown"
    if not serialized.get("trust_status"):
        serialized["trust_status"] = "legacy_untrusted"
    if serialized.get("schema_version") is None:
        serialized["schema_version"] = 1
    serialized.setdefault("quarantine_reason", None)
    serialized["source_ids"] = _serialize_json_field(serialized.get("source_ids"), [])
    serialized["metadata"] = _serialize_json_field(serialized.get("metadata"), {})
    return serialized


def insert_event(event: dict) -> None:
    """Insert a single event. Ignores duplicates by id."""
    conn = _get_conn()
    _ensure_event_table(conn)
    serialized = _serialize_event(event)
    conn.execute("""
        INSERT OR IGNORE INTO biotech_events
        (
            id, date, type, priority, ticker, disease_area, catalyst, sentiment,
            price_impact, source, source_entity, source_url, source_ids, confidence, metadata,
            ticker_scope, source_run_id, query_hash, company_identity, ownership_status,
            trust_status, schema_version, quarantine_reason
        )
        VALUES (
            :id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment,
            :price_impact, :source, :source_entity, :source_url, :source_ids, :confidence, :metadata,
            :ticker_scope, :source_run_id, :query_hash, :company_identity, :ownership_status,
            :trust_status, :schema_version, :quarantine_reason
        )
    """, serialized)
    conn.commit()
    conn.close()


def insert_events(events: list[dict]) -> int:
    """Batch insert events. Returns count of inserted rows."""
    conn = _get_conn()
    _ensure_event_table(conn)
    serialized_events = [_serialize_event(event) for event in events]
    cur = conn.executemany("""
        INSERT OR IGNORE INTO biotech_events
        (
            id, date, type, priority, ticker, disease_area, catalyst, sentiment,
            price_impact, source, source_entity, source_url, source_ids, confidence, metadata,
            ticker_scope, source_run_id, query_hash, company_identity, ownership_status,
            trust_status, schema_version, quarantine_reason
        )
        VALUES (
            :id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment,
            :price_impact, :source, :source_entity, :source_url, :source_ids, :confidence, :metadata,
            :ticker_scope, :source_run_id, :query_hash, :company_identity, :ownership_status,
            :trust_status, :schema_version, :quarantine_reason
        )
    """, serialized_events)
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


def get_events(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
) -> pd.DataFrame:
    """Query events as DataFrame."""
    conn = _get_conn()
    query = "SELECT * FROM biotech_events WHERE ticker = ?"
    params: list = [ticker]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if event_type:
        query += " AND type = ?"
        params.append(event_type)

    query += " ORDER BY date"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_events_for_chart(ticker: str) -> list[dict]:
    """Return events as list of dicts matching BiotechEvent interface."""
    df = get_events(ticker)
    return [_decode_event_row(row) for row in df.to_dict(orient="records")]


def get_trusted_events_for_chart(ticker: str) -> list[dict]:
    """Return trusted chart events for a ticker."""
    conn = _get_conn()
    _ensure_event_table(conn)
    where_clause, params = _trusted_event_predicate(
        ticker,
        TRUSTED_OWNERSHIP_STATUSES,
    )
    rows = conn.execute(
        f"""
        SELECT *
        FROM biotech_events
        WHERE {where_clause}
        ORDER BY date
        """,
        params,
    ).fetchall()
    conn.close()
    return [_decode_event_row(dict(row)) for row in rows]


def get_trusted_events_for_backtest(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Return trusted, backtest-eligible events for a ticker/date range."""
    conn = _get_conn()
    _ensure_event_table(conn)
    where_clause, params = _trusted_event_predicate(
        ticker,
        BACKTEST_TRUSTED_OWNERSHIP_STATUSES,
    )
    query = f"""
        SELECT *
        FROM biotech_events
        WHERE {where_clause}
    """
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if df.empty:
        return df.reset_index(drop=True)

    df["metadata"] = df["metadata"].apply(decode_metadata)
    backtest_mask = df["metadata"].apply(is_metadata_backtest_eligible)
    return df[backtest_mask].reset_index(drop=True)


def mark_legacy_events_untrusted(ticker: str | None = None) -> int:
    """Mark legacy event rows untrusted without deleting them."""
    conn = _get_conn()
    _ensure_event_table(conn)
    params: list[object] = ["legacy row missing trust provenance"]
    query = """
        UPDATE biotech_events
        SET
            trust_status = 'legacy_untrusted',
            schema_version = 1,
            quarantine_reason = COALESCE(NULLIF(quarantine_reason, ''), ?)
        WHERE (
            trust_status IS NULL
            OR trust_status = ''
            OR schema_version IS NULL
            OR schema_version < 2
        )
    """
    if ticker:
        query += " AND UPPER(ticker) = ?"
        params.append(ticker.upper())
    cur = conn.execute(query, params)
    conn.commit()
    updated = cur.rowcount
    conn.close()
    return updated


def _trusted_event_predicate(
    ticker: str,
    ownership_statuses: set[str],
) -> tuple[str, list[object]]:
    trusted_statuses = sorted(TRUSTED_STATUSES)
    ownership_values = sorted(ownership_statuses)
    where_clause = f"""
        ticker_scope IS NOT NULL
        AND UPPER(ticker_scope) = ?
        AND trust_status IN ({_sql_placeholders(trusted_statuses)})
        AND schema_version >= ?
        AND ownership_status IN ({_sql_placeholders(ownership_values)})
    """
    params: list[object] = [
        ticker.upper(),
        *trusted_statuses,
        TRUSTED_SCHEMA_VERSION,
        *ownership_values,
    ]
    return where_clause, params


def _sql_placeholders(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


def _decode_json_field(value: object, default: object, expected_type: type) -> object:
    if value is None or value == "":
        return default.copy()
    if isinstance(value, expected_type):
        return value
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return default.copy()
    return decoded if isinstance(decoded, expected_type) else default.copy()


def _decode_event_row(row: dict) -> dict:
    """Decode JSON-backed event attribution fields for chart consumers."""
    event = dict(row)
    event["source_ids"] = _decode_json_field(event.get("source_ids"), [], list)
    event["metadata"] = _decode_json_field(event.get("metadata"), {}, dict)
    event["confidence"] = event.get("confidence") or "medium"
    return event


def init_fetch_log_table() -> None:
    """Create fetch_log table if not exists."""
    conn = _get_conn()
    _ensure_fetch_log_table(conn)
    conn.commit()
    conn.close()


def _ensure_fetch_log_table(conn: sqlite3.Connection) -> None:
    """Create or migrate fetch_log without dropping source history."""
    conn.execute(FETCH_LOG_TABLE_SQL)
    existing_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(fetch_log)").fetchall()
    }
    for column_name, column_definition in FETCH_LOG_COLUMN_DEFINITIONS.items():
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE fetch_log ADD COLUMN {column_name} {column_definition}")


def record_fetch_attempt(
    ticker: str,
    source: str,
    item_count: int,
    status: str | None = None,
    message: str | None = None,
) -> None:
    """Record a fetch attempt with timestamp, item count, and source status."""
    count = int(item_count or 0)
    source_status = status or ("ready" if count > 0 else "empty")
    detail = str(message) if message else None
    conn = _get_conn()
    _ensure_fetch_log_table(conn)
    conn.execute("""
        INSERT OR REPLACE INTO fetch_log
            (ticker, source, last_fetch_at, item_count, status, message)
        VALUES (?, ?, datetime('now'), ?, ?, ?)
    """, (ticker, source, count, source_status, detail))
    conn.commit()
    conn.close()


def get_last_fetch_at(ticker: str, source: str) -> Optional[str]:
    """Get the last fetch timestamp for a ticker/source pair, or None if never fetched."""
    conn = _get_conn()
    _ensure_fetch_log_table(conn)
    cur = conn.execute(
        "SELECT last_fetch_at FROM fetch_log WHERE ticker = ? AND source = ?",
        (ticker, source)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def get_fetch_log_entries(ticker: str) -> list[dict]:
    """Return fetch log source statuses for a ticker ordered by source."""
    conn = _get_conn()
    _ensure_fetch_log_table(conn)
    cur = conn.execute(
        """
        SELECT
            source,
            last_fetch_at,
            item_count,
            COALESCE(
                status,
                CASE WHEN item_count > 0 THEN 'ready' ELSE 'empty' END
            ) AS status,
            message
        FROM fetch_log
        WHERE ticker = ?
        ORDER BY source
        """,
        (ticker,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
