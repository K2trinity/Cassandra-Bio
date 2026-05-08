from __future__ import annotations


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
    ) == second


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
