from __future__ import annotations

from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID


class UnsupportedUniverseError(ValueError):
    """Raised when a production portfolio requests an unsupported universe."""


def load_universe_tickers(
    *,
    db_path: str | Path | None = None,
    universe_id: str,
    as_of_date: str,
) -> tuple[str, ...]:
    if universe_id != BIOTECH_US_UNIVERSE_ID:
        raise UnsupportedUniverseError(f"Unsupported production universe: {universe_id}")

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT UPPER(ticker) AS ticker
            FROM universe_membership
            WHERE universe_id = ?
              AND member_from <= ?
              AND (member_to IS NULL OR member_to >= ?)
            ORDER BY ticker
            """,
            [universe_id, as_of_date, as_of_date],
        ).fetchall()
    finally:
        conn.close()

    return tuple(str(row[0]).upper() for row in rows)
