from __future__ import annotations

import json


def test_record_provider_fetch_writes_rate_limited_log_with_metadata(tmp_path):
    from src.data_ingestion.provider_log import record_provider_fetch

    db_path = tmp_path / "research.duckdb"

    fetch_id = record_provider_fetch(
        provider="tiingo",
        endpoint="/daily/MRNA/prices",
        request_hash="req_abc123",
        status="rate_limited",
        retry_count=2,
        message="retry after fixed window",
        metadata={"retry_after_seconds": 7.5, "provider_scope": "tiingo"},
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT
                fetch_id,
                provider,
                endpoint,
                request_hash,
                status,
                retry_count,
                message,
                metadata_json
            FROM provider_fetch_log
            WHERE fetch_id = ?
            """,
            [fetch_id],
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        fetch_id,
        "tiingo",
        "/daily/MRNA/prices",
        "req_abc123",
        "rate_limited",
        2,
        "retry after fixed window",
        '{"provider_scope":"tiingo","retry_after_seconds":7.5}',
    )
    assert json.loads(row[7]) == {
        "provider_scope": "tiingo",
        "retry_after_seconds": 7.5,
    }


def test_record_provider_fetch_returns_deterministic_fetch_id_and_replaces_row(
    tmp_path,
):
    from src.data_ingestion.provider_log import record_provider_fetch

    db_path = tmp_path / "research.duckdb"

    first_id = record_provider_fetch(
        provider="sec",
        endpoint="/submissions/CIK0001682852.json",
        request_hash="req_sec_1",
        status="started",
        retry_count=0,
        metadata={"attempt": 1},
        db_path=db_path,
    )
    second_id = record_provider_fetch(
        provider="sec",
        endpoint="/submissions/CIK0001682852.json",
        request_hash="req_sec_1",
        status="success",
        retry_count=1,
        message="cached fixture written",
        metadata={"attempt": 2},
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT status, retry_count, message, metadata_json
            FROM provider_fetch_log
            WHERE fetch_id = ?
            """,
            [first_id],
        ).fetchall()
    finally:
        conn.close()

    assert first_id == second_id
    assert first_id.startswith("fetch_")
    assert rows == [("success", 1, "cached fixture written", '{"attempt":2}')]
