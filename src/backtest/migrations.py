from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from src.backtest.events_db import DB_PATH

MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "20260507_001_event_research_columns",
        (
            "ALTER TABLE biotech_events ADD COLUMN event_timestamp_utc TEXT",
            "ALTER TABLE biotech_events ADD COLUMN release_session TEXT",
            "ALTER TABLE biotech_events ADD COLUMN effective_event_date TEXT",
            "ALTER TABLE biotech_events ADD COLUMN company_security_id TEXT",
            "ALTER TABLE biotech_events ADD COLUMN event_taxonomy_version TEXT",
            "ALTER TABLE biotech_events ADD COLUMN extraction_version TEXT",
            "ALTER TABLE biotech_events ADD COLUMN dedupe_key TEXT",
            "ALTER TABLE biotech_events ADD COLUMN source_published_at TEXT",
            "ALTER TABLE biotech_events ADD COLUMN ingested_at TEXT",
        ),
    ),
    (
        "20260507_002_event_provenance_tables",
        (
            """
            CREATE TABLE IF NOT EXISTS event_source_documents (
                document_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_url TEXT,
                source_entity TEXT,
                published_at TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                payload_hash TEXT,
                payload_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS event_extraction_runs (
                extraction_run_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                extraction_version TEXT NOT NULL,
                started_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                status TEXT,
                input_count INTEGER DEFAULT 0,
                output_count INTEGER DEFAULT 0,
                message TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS event_quality_issues (
                issue_id TEXT PRIMARY KEY,
                event_id TEXT,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """,
        ),
    ),
)


def apply_sqlite_migrations(db_path: str | Path | None = None) -> None:
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _ensure_schema_migrations(conn)
        for migration_id, statements in MIGRATIONS:
            if _migration_applied(conn, migration_id):
                continue
            _apply_statements(conn, statements)
            conn.execute(
                """
                INSERT INTO schema_migrations (migration_id, applied_at)
                VALUES (?, datetime('now'))
                """,
                (migration_id,),
            )
            conn.commit()
    finally:
        conn.close()


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _migration_applied(conn: sqlite3.Connection, migration_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
        (migration_id,),
    ).fetchone()
    return row is not None


def _apply_statements(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                continue
            raise
