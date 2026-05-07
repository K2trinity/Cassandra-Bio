from __future__ import annotations

import sqlite3


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE biotech_events (
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
    )
    conn.execute(
        """
        INSERT INTO biotech_events
            (id, date, type, priority, ticker, catalyst, sentiment, source)
        VALUES
            ('evt-1', '2026-04-19', 'clinical_readout', 2, 'MRNA',
             'Legacy catalyst', 'positive', 'demo')
        """
    )
    conn.commit()
    conn.close()


def _columns(path, table):
    conn = sqlite3.connect(path)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {row[1] for row in rows}


def test_apply_sqlite_migrations_preserves_legacy_events(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM biotech_events").fetchone()[0]
    migration_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    event = conn.execute("SELECT catalyst FROM biotech_events WHERE id = 'evt-1'").fetchone()
    conn.close()

    assert count == 1
    assert event[0] == "Legacy catalyst"
    assert migration_count >= 1


def test_apply_sqlite_migrations_adds_event_research_columns(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)

    columns = _columns(db_path, "biotech_events")
    assert {
        "event_timestamp_utc",
        "release_session",
        "effective_event_date",
        "company_security_id",
        "event_taxonomy_version",
        "extraction_version",
        "dedupe_key",
        "source_published_at",
        "ingested_at",
    }.issubset(columns)


def test_apply_sqlite_migrations_is_idempotent(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)
    apply_sqlite_migrations(db_path)

    conn = sqlite3.connect(db_path)
    migration_rows = conn.execute(
        "SELECT migration_id, COUNT(*) FROM schema_migrations GROUP BY migration_id"
    ).fetchall()
    conn.close()

    assert migration_rows
    assert all(count == 1 for _migration_id, count in migration_rows)


def test_apply_sqlite_migrations_creates_event_provenance_tables(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    conn.close()

    assert {
        "schema_migrations",
        "event_source_documents",
        "event_extraction_runs",
        "event_quality_issues",
    }.issubset(tables)
