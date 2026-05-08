from __future__ import annotations

from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.universe_builder import UniverseSnapshot


def write_universe_snapshot(
    snapshot: UniverseSnapshot,
    *,
    db_path: str | Path | None = None,
) -> None:
    import duckdb

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    payload = snapshot.to_catalog_payload()
    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        new_member_to = _next_member_to_date(conn, snapshot)
        conn.execute(
            """
            DELETE FROM universe_membership
            WHERE universe_id = ?
              AND member_from = ?
            """,
            [snapshot.universe_id, snapshot.as_of_date],
        )
        conn.execute(
            """
            DELETE FROM universe_snapshots
            WHERE universe_id = ?
              AND as_of_date = ?
            """,
            [snapshot.universe_id, snapshot.as_of_date],
        )
        _close_prior_active_members(conn, snapshot)
        conn.execute(
            """
            INSERT OR REPLACE INTO universe_snapshots (
                universe_snapshot_id,
                universe_id,
                as_of_date,
                bias_status,
                survivorship_bias_warning,
                member_count,
                benchmark_tickers_json,
                source_payload_json,
                coverage_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                payload["universe_snapshot_id"],
                payload["universe_id"],
                payload["as_of_date"],
                payload["bias_status"],
                payload["survivorship_bias_warning"],
                payload["member_count"],
                payload["benchmark_tickers_json"],
                payload["source_payload_json"],
                payload["coverage_json"],
            ],
        )
        for member in snapshot.members:
            conn.execute(
                """
                INSERT OR REPLACE INTO universe_membership (
                    universe_id,
                    security_id,
                    ticker,
                    member_from,
                    member_to,
                    weight,
                    membership_source,
                    as_of_date
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                [
                    snapshot.universe_id,
                    member.security_id,
                    member.ticker,
                    snapshot.as_of_date,
                    new_member_to,
                    ",".join(member.source_memberships),
                    snapshot.as_of_date,
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _next_member_to_date(conn, snapshot: UniverseSnapshot) -> str | None:
    row = conn.execute(
        """
        SELECT CAST(MIN(as_of_date) - INTERVAL 1 DAY AS VARCHAR)
        FROM universe_snapshots
        WHERE universe_id = ?
          AND as_of_date > ?
        """,
        [snapshot.universe_id, snapshot.as_of_date],
    ).fetchone()
    return row[0] if row is not None else None


def _close_prior_active_members(conn, snapshot: UniverseSnapshot) -> None:
    conn.execute(
        """
        UPDATE universe_membership
        SET member_to = CAST(? AS DATE) - INTERVAL 1 DAY
        WHERE universe_id = ?
          AND member_from < ?
          AND (member_to IS NULL OR member_to >= ?)
        """,
        [
            snapshot.as_of_date,
            snapshot.universe_id,
            snapshot.as_of_date,
            snapshot.as_of_date,
        ],
    )
