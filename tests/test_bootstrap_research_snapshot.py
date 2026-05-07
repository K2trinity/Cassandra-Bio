from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

import pandas as pd


def test_bootstrap_research_snapshot_script_help_runs_from_repo_root():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/bootstrap_research_snapshot.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--snapshot-date" in result.stdout
    assert "--universe-id" in result.stdout


def test_bootstrap_research_snapshot_creates_snapshot_from_local_ohlc(tmp_path):
    from scripts.bootstrap_research_snapshot import bootstrap_snapshot

    ohlc_dir = tmp_path / "ohlc"
    research_dir = tmp_path / "research"
    db_path = research_dir / "research.duckdb"
    event_db_path = tmp_path / "events.db"
    _write_ohlc_fixture(ohlc_dir / "MRNA.parquet", close=10.5)

    result = bootstrap_snapshot(
        ohlc_dir=ohlc_dir,
        research_dir=research_dir,
        db_path=db_path,
        event_db_path=event_db_path,
        snapshot_date="2026-05-07",
        universe_id="biotech_four_v1",
    )

    assert result["data_snapshot_id"].startswith("snap_20260507_")
    assert result["coverage"] == {"tickers": 1, "rows": 2}
    assert db_path.exists()
    assert event_db_path.exists()
    assert list((research_dir / "prices_daily").rglob("*.parquet"))

    import duckdb

    conn = duckdb.connect(str(db_path))
    row = conn.execute(
        """
        SELECT
            data_snapshot_id,
            universe_id,
            bias_profile,
            price_partition_root,
            event_source_db,
            event_snapshot_hash,
            security_master_hash,
            coverage_json
        FROM data_snapshots
        WHERE data_snapshot_id = ?
        """,
        [result["data_snapshot_id"]],
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == result["data_snapshot_id"]
    assert row[1] == "biotech_four_v1"
    assert row[2] == "survivorship_biased"
    assert row[3] == str(research_dir / "prices_daily")
    assert row[4] == str(event_db_path)
    assert row[5] == _expected_event_source_hash(event_db_path)
    assert row[6] == _expected_ohlc_manifest_hash(ohlc_dir)
    assert json.loads(row[7]) == {"rows": 2, "tickers": 1}


def test_bootstrap_research_snapshot_id_changes_when_local_ohlc_content_changes(
    tmp_path,
):
    from scripts.bootstrap_research_snapshot import bootstrap_snapshot

    event_db_path = tmp_path / "events.db"
    first_ohlc_dir = tmp_path / "ohlc-first"
    second_ohlc_dir = tmp_path / "ohlc-second"
    _write_ohlc_fixture(first_ohlc_dir / "MRNA.parquet", close=10.5)
    _write_ohlc_fixture(second_ohlc_dir / "MRNA.parquet", close=10.75)

    first = bootstrap_snapshot(
        ohlc_dir=first_ohlc_dir,
        research_dir=tmp_path / "research-first",
        db_path=tmp_path / "research-first" / "research.duckdb",
        event_db_path=event_db_path,
        snapshot_date="2026-05-07",
        universe_id="biotech_four_v1",
    )
    second = bootstrap_snapshot(
        ohlc_dir=second_ohlc_dir,
        research_dir=tmp_path / "research-second",
        db_path=tmp_path / "research-second" / "research.duckdb",
        event_db_path=event_db_path,
        snapshot_date="2026-05-07",
        universe_id="biotech_four_v1",
    )

    assert first["data_snapshot_id"] != second["data_snapshot_id"]


def test_bootstrap_research_snapshot_id_changes_when_event_db_content_changes(
    tmp_path,
):
    from scripts.bootstrap_research_snapshot import bootstrap_snapshot
    from src.backtest.migrations import apply_sqlite_migrations

    ohlc_dir = tmp_path / "ohlc"
    _write_ohlc_fixture(ohlc_dir / "MRNA.parquet", close=10.5)
    first_event_db_path = tmp_path / "events-empty.db"
    second_event_db_path = tmp_path / "events-with-row.db"
    apply_sqlite_migrations(second_event_db_path)
    _insert_biotech_event(second_event_db_path, event_id="evt-extra")

    first = bootstrap_snapshot(
        ohlc_dir=ohlc_dir,
        research_dir=tmp_path / "research-first",
        db_path=tmp_path / "research-first" / "research.duckdb",
        event_db_path=first_event_db_path,
        snapshot_date="2026-05-07",
        universe_id="biotech_four_v1",
    )
    second = bootstrap_snapshot(
        ohlc_dir=ohlc_dir,
        research_dir=tmp_path / "research-second",
        db_path=tmp_path / "research-second" / "research.duckdb",
        event_db_path=second_event_db_path,
        snapshot_date="2026-05-07",
        universe_id="biotech_four_v1",
    )

    assert first["data_snapshot_id"] != second["data_snapshot_id"]


def _write_ohlc_fixture(path: Path, *, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": close,
                "volume": 1000,
            },
            {
                "date": "2026-05-04",
                "open": 10.5,
                "high": 12,
                "low": 10,
                "close": 11.5,
                "volume": 1200,
            },
        ]
    ).to_parquet(path, index=False)


def _insert_biotech_event(db_path: Path, *, event_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO biotech_events (
                id,
                date,
                type,
                priority,
                ticker,
                catalyst,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                "2026-05-06",
                "approval",
                1,
                "MRNA",
                "Synthetic approval fixture",
                "test",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _expected_ohlc_manifest_hash(ohlc_dir: Path) -> str:
    manifest = {
        "format": "local_ohlc_manifest_v1",
        "files": [
            {
                "filename": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(ohlc_dir.glob("*.parquet"))
        ],
    }
    return _canonical_hash(manifest)


def _expected_event_source_hash(event_db_path: Path) -> str:
    tables = {}
    conn = sqlite3.connect(event_db_path)
    conn.row_factory = sqlite3.Row
    try:
        for table_name in (
            "schema_migrations",
            "biotech_events",
            "event_source_documents",
            "event_extraction_runs",
            "event_quality_issues",
        ):
            if not _sqlite_table_exists(conn, table_name):
                continue
            columns = [
                row["name"]
                for row in conn.execute(
                    f'PRAGMA table_info("{table_name}")'
                ).fetchall()
            ]
            included_columns = (
                ["migration_id"] if table_name == "schema_migrations" else columns
            )
            column_sql = ", ".join(f'"{column}"' for column in included_columns)
            rows = [
                {
                    column: _json_ready(row[column])
                    for column in included_columns
                }
                for row in conn.execute(f"SELECT {column_sql} FROM {table_name}")
            ]
            tables[table_name] = {
                "columns": included_columns,
                "rows": sorted(rows, key=_canonical_json),
            }
    finally:
        conn.close()
    return _canonical_hash({"format": "local_event_source_v1", "tables": tables})


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        is not None
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "bytes_sha256": sha256(value).hexdigest(),
            "size_bytes": len(value),
        }
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()
