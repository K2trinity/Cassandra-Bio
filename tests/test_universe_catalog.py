from __future__ import annotations


def test_write_universe_snapshot_persists_snapshot_and_members(tmp_path):
    import duckdb

    from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot
    from src.backtest.universe_catalog import write_universe_snapshot

    db_path = tmp_path / "research.duckdb"
    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="nasdaq_screener",
                industry="Biotechnology",
                cik="1682852",
            )
        ],
        as_of_date="2026-05-08",
    )

    write_universe_snapshot(snapshot, db_path=db_path)

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT universe_id, member_count, survivorship_bias_warning
            FROM universe_snapshots
            """
        ).fetchone()
        member = conn.execute(
            """
            SELECT security_id, ticker, membership_source
            FROM universe_membership
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == ("biotech_us_v1", 1, True)
    assert member == ("BIO:MRNA", "MRNA", "nasdaq_screener")
