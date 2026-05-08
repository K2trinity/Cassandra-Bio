from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RESEARCH_DIR = ROOT_DIR / "data" / "research"
RESEARCH_DB_PATH = RESEARCH_DIR / "cassandra_research.duckdb"

CATALOG_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS security_master (
        security_id TEXT PRIMARY KEY,
        current_ticker TEXT,
        company_name TEXT,
        exchange TEXT,
        country TEXT,
        currency TEXT,
        asset_type TEXT,
        sector TEXT,
        industry TEXT,
        list_date DATE,
        delist_date DATE,
        delist_reason TEXT,
        status TEXT,
        source TEXT,
        source_security_id TEXT,
        source_payload_json TEXT,
        as_of_date DATE,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticker_aliases (
        security_id TEXT,
        ticker TEXT,
        exchange TEXT,
        valid_from DATE,
        valid_to DATE,
        source TEXT,
        PRIMARY KEY (security_id, ticker, valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS universe_membership (
        universe_id TEXT,
        security_id TEXT,
        ticker TEXT,
        member_from DATE,
        member_to DATE,
        weight DOUBLE,
        membership_source TEXT,
        as_of_date DATE,
        PRIMARY KEY (universe_id, security_id, member_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS universe_snapshots (
        universe_snapshot_id TEXT PRIMARY KEY,
        universe_id TEXT,
        as_of_date DATE,
        bias_status TEXT,
        survivorship_bias_warning BOOLEAN,
        member_count INTEGER,
        benchmark_tickers_json TEXT,
        source_payload_json TEXT,
        coverage_json TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_snapshots (
        data_snapshot_id TEXT PRIMARY KEY,
        snapshot_date DATE,
        price_source TEXT,
        event_source_db TEXT,
        universe_id TEXT,
        bias_profile TEXT,
        price_partition_root TEXT,
        event_snapshot_hash TEXT,
        security_master_hash TEXT,
        coverage_json TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        run_id TEXT PRIMARY KEY,
        data_snapshot_id TEXT,
        universe_id TEXT,
        split_id TEXT,
        strategy_id TEXT,
        data_mode TEXT,
        bias_profile TEXT,
        parameters_json TEXT,
        metrics_json TEXT,
        coverage_json TEXT,
        bias_warnings_json TEXT,
        created_at TIMESTAMP,
        completed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_fetch_log (
        fetch_id TEXT PRIMARY KEY,
        provider TEXT,
        endpoint TEXT,
        request_hash TEXT,
        status TEXT,
        retry_count INTEGER,
        message TEXT,
        metadata_json TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
        run_id TEXT,
        data_snapshot_id TEXT,
        provider TEXT,
        phase TEXT,
        ticker TEXT,
        endpoint TEXT,
        period_start DATE,
        period_end DATE,
        status TEXT,
        attempt_count INTEGER,
        last_error TEXT,
        updated_at TIMESTAMP,
        PRIMARY KEY (run_id, provider, phase, ticker, endpoint)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_snapshot_manifests (
        data_snapshot_id TEXT PRIMARY KEY,
        manifest_json TEXT,
        manifest_path TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamentals_normalized (
        security_id TEXT,
        ticker TEXT,
        fiscal_period TEXT,
        filing_date DATE,
        source TEXT,
        payload_json TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sec_companyfacts_normalized (
        security_id TEXT,
        ticker TEXT,
        cik TEXT,
        taxonomy TEXT,
        concept TEXT,
        unit TEXT,
        fiscal_year INTEGER,
        fiscal_period TEXT,
        form TEXT,
        filed DATE,
        period_end DATE,
        value DOUBLE,
        source TEXT,
        created_at TIMESTAMP
    )
    """,
)


def initialize_research_database(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else RESEARCH_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        for statement in CATALOG_SQL:
            conn.execute(statement)
    finally:
        conn.close()
    return path
