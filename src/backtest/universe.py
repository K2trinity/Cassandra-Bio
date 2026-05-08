from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.runner import normalize_kline_ticker
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID

_CANONICAL_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class UnsupportedUniverseError(ValueError):
    """Raised when a production portfolio requests an unsupported universe."""


def _validate_as_of_date(as_of_date: str) -> str:
    candidate = str(as_of_date or "").strip()
    if not _CANONICAL_DATE_RE.fullmatch(candidate):
        raise ValueError("as_of_date must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise ValueError("as_of_date must use YYYY-MM-DD format") from exc


def load_universe_tickers(
    *,
    db_path: str | Path | None = None,
    universe_id: str,
    as_of_date: str,
) -> tuple[str, ...]:
    if universe_id != BIOTECH_US_UNIVERSE_ID:
        raise UnsupportedUniverseError(f"Unsupported production universe: {universe_id}")

    resolved_as_of_date = _validate_as_of_date(as_of_date)
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT ticker
            FROM universe_membership
            WHERE universe_id = ?
              AND member_from <= ?
              AND (member_to IS NULL OR member_to >= ?)
            """,
            [universe_id, resolved_as_of_date, resolved_as_of_date],
        ).fetchall()
    finally:
        conn.close()

    tickers = {
        normalized
        for row in rows
        if (normalized := normalize_kline_ticker(row[0])) is not None
    }
    return tuple(sorted(tickers))
