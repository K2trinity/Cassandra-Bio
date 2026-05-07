from __future__ import annotations


def test_initialize_research_database_creates_catalog_tables(tmp_path):
    from src.backtest.research_db import initialize_research_database

    db_path = tmp_path / "research.duckdb"

    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    conn.close()

    assert {
        "security_master",
        "ticker_aliases",
        "universe_membership",
        "data_snapshots",
        "backtest_runs",
    }.issubset(tables)


def test_initialize_research_database_is_idempotent(tmp_path):
    from src.backtest.research_db import initialize_research_database

    db_path = tmp_path / "research.duckdb"

    initialize_research_database(db_path)
    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO security_master
            (security_id, current_ticker, status, source, created_at)
        VALUES
            ('YF:MRNA', 'MRNA', 'active', 'yfinance', CURRENT_TIMESTAMP)
        """
    )
    rows = conn.execute(
        "SELECT current_ticker FROM security_master WHERE security_id = 'YF:MRNA'"
    ).fetchall()
    conn.close()

    assert rows == [("MRNA",)]


def test_research_paths_are_under_data_research():
    from src.backtest.research_db import RESEARCH_DIR, RESEARCH_DB_PATH

    assert RESEARCH_DIR.as_posix().endswith("data/research")
    assert RESEARCH_DB_PATH.name == "cassandra_research.duckdb"
