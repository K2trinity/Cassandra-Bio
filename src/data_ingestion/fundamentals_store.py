from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


def write_fundamentals_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    ticker: str,
    db_path: str | Path | None = None,
) -> int:
    normalized_source = _normalize_source(source)
    normalized_ticker = _normalize_ticker(ticker)
    payloads = [dict(row) for row in rows]
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            DELETE FROM fundamentals_normalized
            WHERE source = ? AND ticker = ?
            """,
            [normalized_source, normalized_ticker],
        )
        for row in payloads:
            conn.execute(
                """
                INSERT INTO fundamentals_normalized (
                    security_id,
                    ticker,
                    fiscal_period,
                    filing_date,
                    source,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    str(row.get("security_id") or ""),
                    normalized_ticker,
                    str(row.get("fiscal_period") or ""),
                    row.get("filing_date") or row.get("filed"),
                    normalized_source,
                    json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return len(payloads)


def _normalize_source(source: str) -> str:
    normalized = str(source).strip().lower()
    if not normalized:
        raise ValueError("source must be a non-empty string.")
    return normalized


def _normalize_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    if not normalized:
        raise ValueError("ticker must be a non-empty string.")
    return normalized
