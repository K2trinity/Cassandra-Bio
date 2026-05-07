from __future__ import annotations

import json

import pytest


def _build_snapshot(
    *,
    snapshot_date: str = "2026-05-07",
    price_source: str = "yfinance",
    event_source_db: str = "events.db",
    universe_id: str = "biotech_four_v1",
    bias_profile: str = "survivorship_biased",
    price_partition_root: str = "data/research/prices_daily",
    event_snapshot_hash: str = "events-hash",
    security_master_hash: str = "security-hash",
    coverage: dict[str, object] | None = None,
):
    from src.backtest.snapshot_builder import DataSnapshot, build_data_snapshot_id

    data_snapshot_id = build_data_snapshot_id(
        snapshot_date=snapshot_date,
        price_source=price_source,
        universe_id=universe_id,
        security_master_hash=security_master_hash,
        event_snapshot_hash=event_snapshot_hash,
    )
    return DataSnapshot(
        data_snapshot_id=data_snapshot_id,
        snapshot_date=snapshot_date,
        price_source=price_source,
        event_source_db=event_source_db,
        universe_id=universe_id,
        bias_profile=bias_profile,
        price_partition_root=price_partition_root,
        event_snapshot_hash=event_snapshot_hash,
        security_master_hash=security_master_hash,
        coverage=coverage or {"tickers": 4, "rows": 3600},
    )


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


def test_build_data_snapshot_id_rejects_non_canonical_date_strings():
    from src.backtest.snapshot_builder import build_data_snapshot_id

    invalid_dates = [
        "2026-5-7",
        "2026-05-07T00:00:00",
        "2026-05-07 ",
        "2026-02-30",
    ]

    for snapshot_date in invalid_dates:
        with pytest.raises(ValueError):
            build_data_snapshot_id(
                snapshot_date=snapshot_date,
                price_source="yfinance",
                universe_id="biotech_four_v1",
                security_master_hash="security-hash",
                event_snapshot_hash="events-hash",
            )


def test_insert_data_snapshot_writes_duckdb_row(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    snapshot = _build_snapshot()

    insert_data_snapshot(snapshot, db_path=db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    row = conn.execute(
        """
        SELECT data_snapshot_id, bias_profile, coverage_json
        FROM data_snapshots
        WHERE data_snapshot_id = ?
        """,
        [snapshot.data_snapshot_id],
    ).fetchone()
    conn.close()

    assert row[0] == snapshot.data_snapshot_id
    assert row[1] == "survivorship_biased"
    assert row[2] == '{"rows":3600,"tickers":4}'
    assert json.loads(row[2]) == {"tickers": 4, "rows": 3600}


def test_insert_data_snapshot_is_idempotent_for_same_metadata(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    snapshot = _build_snapshot()

    insert_data_snapshot(snapshot, db_path=db_path)
    insert_data_snapshot(snapshot, db_path=db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    row_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM data_snapshots
        WHERE data_snapshot_id = ?
        """,
        [snapshot.data_snapshot_id],
    ).fetchone()[0]
    conn.close()

    assert row_count == 1


def test_insert_data_snapshot_rejects_same_id_with_different_metadata(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import DataSnapshot, SnapshotMetadataError
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    snapshot = _build_snapshot()
    changed_snapshot = DataSnapshot(
        data_snapshot_id=snapshot.data_snapshot_id,
        snapshot_date=snapshot.snapshot_date,
        price_source=snapshot.price_source,
        event_source_db=snapshot.event_source_db,
        universe_id=snapshot.universe_id,
        bias_profile=snapshot.bias_profile,
        price_partition_root=snapshot.price_partition_root,
        event_snapshot_hash=snapshot.event_snapshot_hash,
        security_master_hash=snapshot.security_master_hash,
        coverage={"tickers": 4, "rows": 3601},
    )

    insert_data_snapshot(snapshot, db_path=db_path)

    with pytest.raises(SnapshotMetadataError):
        insert_data_snapshot(changed_snapshot, db_path=db_path)


def test_insert_data_snapshot_rejects_mismatched_snapshot_id(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import DataSnapshot, SnapshotMetadataError
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    snapshot = DataSnapshot(
        data_snapshot_id="snap_20260507_wrong",
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

    with pytest.raises(SnapshotMetadataError):
        insert_data_snapshot(snapshot, db_path=db_path)


def test_data_snapshot_freezes_coverage_input(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    coverage = {"tickers": 4, "rows": 3600}
    snapshot = _build_snapshot(coverage=coverage)
    coverage["rows"] = 9999

    insert_data_snapshot(snapshot, db_path=db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    coverage_json = conn.execute(
        """
        SELECT coverage_json
        FROM data_snapshots
        WHERE data_snapshot_id = ?
        """,
        [snapshot.data_snapshot_id],
    ).fetchone()
    conn.close()

    assert coverage_json[0] == '{"rows":3600,"tickers":4}'


def test_data_snapshot_deep_freezes_nested_coverage_input(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    coverage = {
        "rows": 3600,
        "by_ticker": {"MRNA": 900},
        "tickers": ["MRNA"],
    }
    snapshot = _build_snapshot(coverage=coverage)

    coverage["by_ticker"]["MRNA"] = 999
    coverage["tickers"].append("JNJ")

    with pytest.raises(TypeError):
        snapshot.coverage["by_ticker"]["MRNA"] = 999
    with pytest.raises(AttributeError):
        snapshot.coverage["tickers"].append("JNJ")

    insert_data_snapshot(snapshot, db_path=db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    coverage_json = conn.execute(
        """
        SELECT coverage_json
        FROM data_snapshots
        WHERE data_snapshot_id = ?
        """,
        [snapshot.data_snapshot_id],
    ).fetchone()[0]
    conn.close()

    assert coverage_json == '{"by_ticker":{"MRNA":900},"rows":3600,"tickers":["MRNA"]}'
    assert json.loads(coverage_json) == {
        "by_ticker": {"MRNA": 900},
        "rows": 3600,
        "tickers": ["MRNA"],
    }


def test_insert_data_snapshot_rejects_non_finite_coverage(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.snapshot_builder import insert_data_snapshot

    db_path = initialize_research_database(tmp_path / "research.duckdb")

    for value in [float("nan"), float("inf")]:
        snapshot = _build_snapshot(coverage={"tickers": 4, "bad": value})
        with pytest.raises(ValueError):
            insert_data_snapshot(snapshot, db_path=db_path)
