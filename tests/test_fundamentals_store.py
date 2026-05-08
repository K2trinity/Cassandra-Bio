from __future__ import annotations

import json

import pytest


def test_write_fundamentals_rows_replaces_same_source_ticker_rows(tmp_path):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    first_count = write_fundamentals_rows(
        [
            {
                "security_id": "FMP:MRNA",
                "ticker": "MRNA",
                "fiscal_period": "2026-Q1",
                "filing_date": "2026-05-01",
                "cash_and_equivalents": 100.0,
            },
            {
                "security_id": "FMP:MRNA",
                "ticker": "MRNA",
                "fiscal_period": "2026-Q2",
                "filing_date": "2026-08-01",
                "cash_and_equivalents": 90.0,
            },
        ],
        source=" FMP ",
        ticker=" mrna ",
        db_path=db_path,
    )
    second_count = write_fundamentals_rows(
        [
            {
                "security_id": "FMP:MRNA",
                "ticker": "MRNA",
                "fiscal_period": "2026-Q3",
                "filing_date": "2026-11-01",
                "cash_and_equivalents": 80.0,
            }
        ],
        source="fmp",
        ticker="MRNA",
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute(
            """
            SELECT
                security_id,
                ticker,
                fiscal_period,
                CAST(filing_date AS VARCHAR),
                source,
                payload_json
            FROM fundamentals_normalized
            ORDER BY fiscal_period
            """
        ).fetchall()
    finally:
        conn.close()

    assert first_count == 2
    assert second_count == 1
    assert len(stored) == 1
    assert stored[0][:5] == ("FMP:MRNA", "MRNA", "2026-Q3", "2026-11-01", "fmp")
    assert json.loads(stored[0][5])["cash_and_equivalents"] == 80.0


def test_write_fundamentals_rows_stores_deterministic_payload_json(tmp_path):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    write_fundamentals_rows(
        [
            {
                "ticker": "mrna",
                "security_id": "FMP:MRNA",
                "filing_date": "2026-05-01",
                "fiscal_period": "2026-Q1",
                "cash_and_equivalents": 100.0,
            }
        ],
        source="FMP",
        ticker="mrna",
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        payload_json = conn.execute(
            "SELECT payload_json FROM fundamentals_normalized"
        ).fetchone()[0]
    finally:
        conn.close()

    assert payload_json == (
        '{"cash_and_equivalents":100.0,"filing_date":"2026-05-01",'
        '"fiscal_period":"2026-Q1","security_id":"FMP:MRNA","ticker":"mrna"}'
    )


@pytest.mark.parametrize(
    ("source", "ticker", "match"),
    [
        ("", "MRNA", "source"),
        (" ", "MRNA", "source"),
        ("fmp", "", "ticker"),
        ("fmp", " ", "ticker"),
    ],
)
def test_write_fundamentals_rows_rejects_empty_source_or_ticker(
    tmp_path, source, ticker, match
):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    with pytest.raises(ValueError, match=match):
        write_fundamentals_rows(
            [],
            source=source,
            ticker=ticker,
            db_path=tmp_path / "research.duckdb",
        )
