from __future__ import annotations

import json


def test_build_data_snapshot_id_is_deterministic():
    from src.backtest.snapshot_builder import build_data_snapshot_id

    first = build_data_snapshot_id(
        snapshot_date="2026-05-07",
        price_source="yfinance",
        universe_id="biotech_four_v1",
        security_master_hash="abc",
        event_snapshot_hash="def",
    )
    second = build_data_snapshot_id(
        snapshot_date="2026-05-07",
        price_source="yfinance",
        universe_id="biotech_four_v1",
        security_master_hash="abc",
        event_snapshot_hash="def",
    )

    assert first == second
    assert first.startswith("snap_20260507_")


def test_insert_data_snapshot_writes_duckdb_row(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import DataSnapshot, insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    snapshot = DataSnapshot(
        data_snapshot_id="snap_20260507_test",
        snapshot_date="2026-05-07",
        price_source="yfinance",
        event_source_db="events.db",
        universe_id="biotech_four_v1",
        bias_profile="survivorship_biased",
        price_partition_root="data/research/prices_daily",
        event_snapshot_hash="events-hash",
        security_master_hash="security-hash",
        coverage={"tickers": 4, "rows": 3600},
    )

    insert_data_snapshot(snapshot, db_path=db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    row = conn.execute(
        """
        SELECT data_snapshot_id, bias_profile, coverage_json
        FROM data_snapshots
        WHERE data_snapshot_id = 'snap_20260507_test'
        """
    ).fetchone()
    conn.close()

    assert row[0] == "snap_20260507_test"
    assert row[1] == "survivorship_biased"
    assert json.loads(row[2]) == {"tickers": 4, "rows": 3600}
