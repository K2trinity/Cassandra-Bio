from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from src.backtest import events_db

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
    path = Path(db_path) if db_path is not None else events_db.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        _setup_database(conn)
        for migration_id, statements in MIGRATIONS:
            _apply_migration(conn, migration_id, statements)
    finally:
        conn.close()


def _setup_database(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_base_event_table(conn)
        _ensure_base_event_index(conn)
        _ensure_schema_migrations(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_base_event_table(conn: sqlite3.Connection) -> None:
    conn.execute(events_db.EVENT_TABLE_SQL)
    for column_name, column_definition in events_db.EVENT_COLUMN_DEFINITIONS.items():
        if not _column_exists(conn, "biotech_events", column_name):
            try:
                conn.execute(
                    f"ALTER TABLE biotech_events ADD COLUMN {column_name} {column_definition}"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    continue
                raise


def _ensure_base_event_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_ticker_date
        ON biotech_events(ticker, date)
        """
    )


def _column_exists(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    return any(
        row[1] == column_name
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    )


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _apply_migration(
    conn: sqlite3.Connection,
    migration_id: str,
    statements: Iterable[str],
) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _migration_applied(conn, migration_id):
            conn.commit()
            return
        _apply_statements(conn, statements)
        conn.execute(
            """
            INSERT INTO schema_migrations (migration_id, applied_at)
            VALUES (?, datetime('now'))
            """,
            (migration_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
