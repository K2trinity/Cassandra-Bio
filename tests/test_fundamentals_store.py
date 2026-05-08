from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import numpy as np
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


def test_write_fundamentals_rows_empty_is_noop_and_preserves_existing_rows(tmp_path):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    write_fundamentals_rows(
        [
            {
                "security_id": "FMP:MRNA",
                "ticker": "MRNA",
                "fiscal_period": "2026-Q1",
                "filing_date": "2026-05-01",
                "cash_and_equivalents": 100.0,
            }
        ],
        source="fmp",
        ticker="MRNA",
        db_path=db_path,
    )

    count = write_fundamentals_rows(
        [],
        source="fmp",
        ticker="MRNA",
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        stored_count = conn.execute(
            "SELECT COUNT(*) FROM fundamentals_normalized"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 0
    assert stored_count == 1


def test_write_fundamentals_rows_canonicalizes_dates_decimal_and_numpy_payloads(
    tmp_path,
):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    write_fundamentals_rows(
        [
            {
                "ticker": np.str_("mrna"),
                "security_id": "FMP:MRNA",
                "filed": datetime(2026, 5, 1, 14, 30),
                "fiscal_period": np.str_("2026-Q1"),
                "cash_and_equivalents": Decimal("100.50"),
                "shares": np.int64(7),
                "margin": np.float64(0.25),
                "as_of": date(2026, 5, 2),
            }
        ],
        source="FMP",
        ticker="mrna",
        db_path=db_path,
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute(
            """
            SELECT CAST(filing_date AS VARCHAR), payload_json
            FROM fundamentals_normalized
            """
        ).fetchone()
    finally:
        conn.close()

    assert stored[0] == "2026-05-01"
    assert json.loads(stored[1]) == {
        "as_of": "2026-05-02",
        "cash_and_equivalents": "100.50",
        "filed": "2026-05-01",
        "fiscal_period": "2026-Q1",
        "margin": 0.25,
        "security_id": "FMP:MRNA",
        "shares": 7,
        "ticker": "mrna",
    }
    assert stored[1] == (
        '{"as_of":"2026-05-02","cash_and_equivalents":"100.50",'
        '"filed":"2026-05-01","fiscal_period":"2026-Q1","margin":0.25,'
        '"security_id":"FMP:MRNA","shares":7,"ticker":"mrna"}'
    )


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"security_id": "", "fiscal_period": "2026-Q1"}, "row 0.*security_id"),
        ({"security_id": "FMP:MRNA", "fiscal_period": " "}, "row 0.*fiscal_period"),
    ],
)
def test_write_fundamentals_rows_rejects_missing_identity_fields(
    tmp_path, row, match
):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    with pytest.raises(ValueError, match=match):
        write_fundamentals_rows(
            [row],
            source="fmp",
            ticker="MRNA",
            db_path=tmp_path / "research.duckdb",
        )


def test_write_fundamentals_rows_rejects_non_finite_before_replacing_rows(tmp_path):
    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    write_fundamentals_rows(
        [
            {
                "security_id": "FMP:MRNA",
                "ticker": "MRNA",
                "fiscal_period": "2026-Q1",
                "filing_date": "2026-05-01",
                "cash_and_equivalents": 100.0,
            }
        ],
        source="fmp",
        ticker="MRNA",
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="row 0.*cash_and_equivalents.*finite"):
        write_fundamentals_rows(
            [
                {
                    "security_id": "FMP:MRNA",
                    "ticker": "MRNA",
                    "fiscal_period": "2026-Q2",
                    "filing_date": "2026-08-01",
                    "cash_and_equivalents": np.nan,
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
            SELECT fiscal_period, payload_json
            FROM fundamentals_normalized
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(stored) == 1
    assert stored[0][0] == "2026-Q1"
    assert json.loads(stored[0][1])["cash_and_equivalents"] == 100.0


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
