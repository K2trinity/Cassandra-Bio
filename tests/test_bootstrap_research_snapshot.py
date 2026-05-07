from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

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
    ohlc_dir.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
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
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)

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
    assert json.loads(row[5]) == {"rows": 2, "tickers": 1}
