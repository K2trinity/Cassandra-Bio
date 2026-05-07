from __future__ import annotations

import threading
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest


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


def _tables(path):
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    conn.close()
    return {row[0] for row in rows}


def _indexes(path, table):
    conn = sqlite3.connect(path)
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    conn.close()
    return {row[1] for row in rows}


def _migration_rows(path):
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT migration_id, COUNT(*) FROM schema_migrations GROUP BY migration_id"
    ).fetchall()
    conn.close()
    return rows


def _migration_ids(path):
    return {migration_id for migration_id, _count in _migration_rows(path)}


def _research_columns():
    return {
        "event_timestamp_utc",
        "release_session",
        "effective_event_date",
        "company_security_id",
        "event_taxonomy_version",
        "extraction_version",
        "dedupe_key",
        "source_published_at",
        "ingested_at",
    }


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
    assert _research_columns().issubset(columns)


def test_apply_sqlite_migrations_is_idempotent(tmp_path):
    from src.backtest.migrations import MIGRATIONS, apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)
    apply_sqlite_migrations(db_path)

    migration_rows = _migration_rows(db_path)
    migration_ids = {migration_id for migration_id, _count in migration_rows}

    assert migration_ids == {migration_id for migration_id, _statements in MIGRATIONS}
    assert all(count == 1 for _migration_id, count in migration_rows)


def test_apply_sqlite_migrations_creates_event_provenance_tables(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)

    apply_sqlite_migrations(db_path)

    tables = _tables(db_path)

    assert {
        "schema_migrations",
        "event_source_documents",
        "event_extraction_runs",
        "event_quality_issues",
    }.issubset(tables)


def test_apply_sqlite_migrations_initializes_empty_event_db(tmp_path):
    from src.backtest.migrations import MIGRATIONS, apply_sqlite_migrations

    db_path = tmp_path / "events.db"

    apply_sqlite_migrations(db_path)

    assert "biotech_events" in _tables(db_path)
    assert _research_columns().issubset(_columns(db_path, "biotech_events"))
    assert {
        "schema_migrations",
        "event_source_documents",
        "event_extraction_runs",
        "event_quality_issues",
    }.issubset(_tables(db_path))
    assert _migration_ids(db_path) == {
        migration_id for migration_id, _statements in MIGRATIONS
    }


def test_apply_sqlite_migrations_uses_current_default_db_path(tmp_path, monkeypatch):
    from src.backtest import events_db, migrations

    stale_path = tmp_path / "stale.db"
    current_path = tmp_path / "current.db"
    monkeypatch.setattr(migrations, "DB_PATH", stale_path, raising=False)
    monkeypatch.setattr(events_db, "DB_PATH", current_path)

    migrations.apply_sqlite_migrations()

    assert "biotech_events" in _tables(current_path)
    assert not stale_path.exists()


def test_apply_sqlite_migrations_initializes_empty_event_db_concurrently(
    tmp_path,
    monkeypatch,
):
    from src.backtest import events_db, migrations

    db_path = tmp_path / "events.db"
    original_connect = sqlite3.connect
    barrier = threading.Barrier(2)

    class RaceConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._has_write_lock = False

        def execute(self, sql, parameters=(), /):
            normalized_sql = " ".join(str(sql).lower().split())
            if normalized_sql == "begin immediate":
                self._has_write_lock = True
            cursor = super().execute(sql, parameters)
            if (
                normalized_sql.startswith("pragma table_info(biotech_events)")
                and not self._has_write_lock
            ):
                barrier.wait(timeout=10)
            return cursor

    def connect(*args, **kwargs):
        kwargs["factory"] = RaceConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(
        migrations,
        "sqlite3",
        SimpleNamespace(
            Connection=sqlite3.Connection,
            OperationalError=sqlite3.OperationalError,
            connect=connect,
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(migrations.apply_sqlite_migrations, db_path)
            for _attempt in range(2)
        ]
        errors = []
        for future in futures:
            try:
                future.result(timeout=20)
            except Exception as exc:
                errors.append(exc)

    assert errors == []
    event_columns = _columns(db_path, "biotech_events")
    assert set(events_db.EVENT_COLUMN_DEFINITIONS).issubset(event_columns)
    assert _research_columns().issubset(event_columns)
    assert _migration_ids(db_path) == {
        migration_id for migration_id, _statements in migrations.MIGRATIONS
    }


def test_apply_sqlite_migrations_initializes_empty_event_db_index(tmp_path):
    from src.backtest.migrations import apply_sqlite_migrations

    db_path = tmp_path / "events.db"

    apply_sqlite_migrations(db_path)

    assert "idx_events_ticker_date" in _indexes(db_path, "biotech_events")


def test_apply_sqlite_migrations_rolls_back_failed_migration(tmp_path, monkeypatch):
    from src.backtest import migrations

    db_path = tmp_path / "events.db"
    _legacy_db(db_path)
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        (
            (
                "test_failed_migration",
                (
                    "ALTER TABLE biotech_events ADD COLUMN transient_column TEXT",
                    "CREATE TABLE broken_sql (",
                ),
            ),
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        migrations.apply_sqlite_migrations(db_path)

    assert "transient_column" not in _columns(db_path, "biotech_events")
    assert _migration_rows(db_path) == []
