# src/backtest/events_db.py
"""SQLite event store for biotech catalysts."""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "events.db"


EVENT_COLUMN_DEFINITIONS = {
    "source_entity": "TEXT",
    "source_url": "TEXT",
    "source_ids": "TEXT",
    "confidence": "TEXT DEFAULT 'medium'",
    "metadata": "TEXT",
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
    conn.execute("""
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
    """)
    _ensure_columns(conn)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ticker_date
        ON biotech_events(ticker, date)
    """)
    conn.commit()
    conn.close()


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
    serialized["source_ids"] = _serialize_json_field(serialized.get("source_ids"), [])
    serialized["metadata"] = _serialize_json_field(serialized.get("metadata"), {})
    return serialized


def insert_event(event: dict) -> None:
    """Insert a single event. Ignores duplicates by id."""
    conn = _get_conn()
    serialized = _serialize_event(event)
    conn.execute("""
        INSERT OR IGNORE INTO biotech_events
        (
            id, date, type, priority, ticker, disease_area, catalyst, sentiment,
            price_impact, source, source_entity, source_url, source_ids, confidence, metadata
        )
        VALUES (
            :id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment,
            :price_impact, :source, :source_entity, :source_url, :source_ids, :confidence, :metadata
        )
    """, serialized)
    conn.commit()
    conn.close()


def insert_events(events: list[dict]) -> int:
    """Batch insert events. Returns count of inserted rows."""
    conn = _get_conn()
    serialized_events = [_serialize_event(event) for event in events]
    cur = conn.executemany("""
        INSERT OR IGNORE INTO biotech_events
        (
            id, date, type, priority, ticker, disease_area, catalyst, sentiment,
            price_impact, source, source_entity, source_url, source_ids, confidence, metadata
        )
        VALUES (
            :id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment,
            :price_impact, :source, :source_entity, :source_url, :source_ids, :confidence, :metadata
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            ticker TEXT NOT NULL,
            source TEXT NOT NULL,
            last_fetch_at TEXT NOT NULL,
            item_count INTEGER DEFAULT 0,
            PRIMARY KEY (ticker, source)
        )
    """)
    conn.commit()
    conn.close()


def record_fetch_attempt(ticker: str, source: str, item_count: int) -> None:
    """Record a fetch attempt with timestamp and item count."""
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO fetch_log (ticker, source, last_fetch_at, item_count)
        VALUES (?, ?, datetime('now'), ?)
    """, (ticker, source, item_count))
    conn.commit()
    conn.close()


def get_last_fetch_at(ticker: str, source: str) -> Optional[str]:
    """Get the last fetch timestamp for a ticker/source pair, or None if never fetched."""
    conn = _get_conn()
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
    cur = conn.execute(
        """
        SELECT source, last_fetch_at, item_count
        FROM fetch_log
        WHERE ticker = ?
        ORDER BY source
        """,
        (ticker,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
