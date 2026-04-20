# src/backtest/events_db.py
"""SQLite event store for biotech catalysts."""

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "events.db"


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
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ticker_date
        ON biotech_events(ticker, date)
    """)
    conn.commit()
    conn.close()


def insert_event(event: dict) -> None:
    """Insert a single event. Ignores duplicates by id."""
    conn = _get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO biotech_events
        (id, date, type, priority, ticker, disease_area, catalyst, sentiment, price_impact, source)
        VALUES (:id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment, :price_impact, :source)
    """, event)
    conn.commit()
    conn.close()


def insert_events(events: list[dict]) -> int:
    """Batch insert events. Returns count of inserted rows."""
    conn = _get_conn()
    cur = conn.executemany("""
        INSERT OR IGNORE INTO biotech_events
        (id, date, type, priority, ticker, disease_area, catalyst, sentiment, price_impact, source)
        VALUES (:id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment, :price_impact, :source)
    """, events)
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
    return df.to_dict(orient="records")


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
