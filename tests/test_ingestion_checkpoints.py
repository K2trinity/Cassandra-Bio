from __future__ import annotations


def test_initialize_research_database_migrates_legacy_checkpoint_identity(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        get_checkpoint,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE ingestion_checkpoints (
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
            """
        )
        conn.execute(
            """
            INSERT INTO ingestion_checkpoints (
                run_id,
                data_snapshot_id,
                provider,
                phase,
                ticker,
                endpoint,
                period_start,
                period_end,
                status,
                attempt_count,
                last_error,
                updated_at
            )
            VALUES (
                'run-legacy',
                'snap-1',
                'tiingo',
                'prices',
                'MRNA',
                '/tiingo/daily/MRNA/prices',
                '2020-03-01',
                '2020-03-31',
                'success',
                1,
                NULL,
                CURRENT_TIMESTAMP
            )
            """
        )
    finally:
        conn.close()

    initialize_research_database(db_path)
    april = IngestionCheckpoint(
        run_id="run-legacy",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-04-01",
        period_end="2020-04-30",
        status="failed",
        attempt_count=2,
        last_error="retry later",
    )

    record_checkpoint(april, db_path=db_path)

    assert get_checkpoint(
        db_path=db_path,
        run_id="run-legacy",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-03-01",
        period_end="2020-03-31",
    ) == IngestionCheckpoint(
        run_id="run-legacy",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-03-01",
        period_end="2020-03-31",
        status="success",
        attempt_count=1,
        last_error=None,
    )
    assert get_checkpoint(
        db_path=db_path,
        run_id="run-legacy",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-04-01",
        period_end="2020-04-30",
    ) == april


def test_record_checkpoint_upserts_resumable_unit(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        get_checkpoint,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    checkpoint = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
        status="success",
        attempt_count=1,
        last_error=None,
    )

    record_checkpoint(checkpoint, db_path=db_path)
    loaded = get_checkpoint(
        db_path=db_path,
        run_id="run-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
    )

    assert loaded == checkpoint


def test_record_checkpoint_replaces_existing_unit(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        get_checkpoint,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    first = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="Tiingo",
        phase="Prices",
        ticker="mrna",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
        status="failed",
        attempt_count=1,
        last_error="timeout",
    )
    second = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
        status="success",
        attempt_count=2,
        last_error=None,
    )

    record_checkpoint(first, db_path=db_path)
    record_checkpoint(second, db_path=db_path)

    assert get_checkpoint(
        db_path=db_path,
        run_id="run-1",
        provider="TIINGO",
        phase="PRICES",
        ticker="mrna",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
    ) == second


def test_date_window_checkpoints_coexist_for_same_endpoint(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        get_checkpoint,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    january = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
        status="success",
        attempt_count=1,
        last_error=None,
    )
    february = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-02-01",
        period_end="2020-02-29",
        status="failed",
        attempt_count=2,
        last_error="rate limited",
    )

    record_checkpoint(january, db_path=db_path)
    record_checkpoint(february, db_path=db_path)

    assert get_checkpoint(
        db_path=db_path,
        run_id="run-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
    ) == january
    assert get_checkpoint(
        db_path=db_path,
        run_id="run-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-02-01",
        period_end="2020-02-29",
    ) == february


def test_completed_checkpoint_is_detected_case_insensitively(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        is_completed,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    record_checkpoint(
        IngestionCheckpoint(
            run_id="run-1",
            data_snapshot_id="snap-1",
            provider="sec",
            phase="companyfacts",
            ticker="mrna",
            endpoint="/companyfacts/MRNA",
            period_start=None,
            period_end=None,
            status="success",
            attempt_count=1,
            last_error=None,
        ),
        db_path=db_path,
    )

    assert is_completed(
        db_path=db_path,
        run_id="run-1",
        provider="SEC",
        phase="companyfacts",
        ticker="MRNA",
        endpoint="/companyfacts/MRNA",
    ) is True


def test_failed_checkpoint_is_not_completed(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        is_completed,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    record_checkpoint(
        IngestionCheckpoint(
            run_id="run-1",
            data_snapshot_id="snap-1",
            provider="sec",
            phase="companyfacts",
            ticker="MRNA",
            endpoint="/companyfacts/MRNA",
            period_start=None,
            period_end=None,
            status="failed",
            attempt_count=1,
            last_error="bad response",
        ),
        db_path=db_path,
    )

    assert is_completed(
        db_path=db_path,
        run_id="run-1",
        provider="sec",
        phase="companyfacts",
        ticker="MRNA",
        endpoint="/companyfacts/MRNA",
    ) is False
