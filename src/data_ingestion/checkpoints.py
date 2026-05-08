from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


@dataclass(frozen=True)
class IngestionCheckpoint:
    run_id: str
    data_snapshot_id: str
    provider: str
    phase: str
    ticker: str
    endpoint: str
    period_start: str | None
    period_end: str | None
    status: str
    attempt_count: int
    last_error: str | None


def record_checkpoint(
    checkpoint: IngestionCheckpoint,
    *,
    db_path: str | Path | None = None,
) -> None:
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    row = _normalized(checkpoint)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            DELETE FROM ingestion_checkpoints
            WHERE run_id = ?
              AND provider = ?
              AND phase = ?
              AND ticker = ?
              AND endpoint = ?
              AND period_start = ?
              AND period_end = ?
            """,
            [
                row.run_id,
                row.provider,
                row.phase,
                row.ticker,
                row.endpoint,
                _period_key(row.period_start),
                _period_key(row.period_end),
            ],
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                row.run_id,
                row.data_snapshot_id,
                row.provider,
                row.phase,
                row.ticker,
                row.endpoint,
                _period_key(row.period_start),
                _period_key(row.period_end),
                row.status,
                row.attempt_count,
                row.last_error,
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_checkpoint(
    *,
    db_path: str | Path | None = None,
    run_id: str,
    provider: str,
    phase: str,
    ticker: str,
    endpoint: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> IngestionCheckpoint | None:
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        row = conn.execute(
            """
            SELECT
                run_id,
                data_snapshot_id,
                provider,
                phase,
                ticker,
                endpoint,
                NULLIF(period_start, ''),
                NULLIF(period_end, ''),
                status,
                attempt_count,
                last_error
            FROM ingestion_checkpoints
            WHERE run_id = ?
              AND provider = ?
              AND phase = ?
              AND ticker = ?
              AND endpoint = ?
              AND period_start = ?
              AND period_end = ?
            """,
            [
                _require_text(run_id, "run_id"),
                _provider_phase(provider, "provider"),
                _provider_phase(phase, "phase"),
                _ticker(ticker),
                _require_text(endpoint, "endpoint"),
                _period_key(period_start),
                _period_key(period_end),
            ],
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return IngestionCheckpoint(*row)


def is_completed(
    *,
    db_path: str | Path | None = None,
    run_id: str,
    provider: str,
    phase: str,
    ticker: str,
    endpoint: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> bool:
    checkpoint = get_checkpoint(
        db_path=db_path,
        run_id=run_id,
        provider=provider,
        phase=phase,
        ticker=ticker,
        endpoint=endpoint,
        period_start=period_start,
        period_end=period_end,
    )
    return checkpoint is not None and checkpoint.status == "success"


def _normalized(checkpoint: IngestionCheckpoint) -> IngestionCheckpoint:
    return IngestionCheckpoint(
        run_id=_require_text(checkpoint.run_id, "run_id"),
        data_snapshot_id=_require_text(checkpoint.data_snapshot_id, "data_snapshot_id"),
        provider=_provider_phase(checkpoint.provider, "provider"),
        phase=_provider_phase(checkpoint.phase, "phase"),
        ticker=_ticker(checkpoint.ticker),
        endpoint=_require_text(checkpoint.endpoint, "endpoint"),
        period_start=_period_value(checkpoint.period_start),
        period_end=_period_value(checkpoint.period_end),
        status=_provider_phase(checkpoint.status, "status"),
        attempt_count=int(checkpoint.attempt_count),
        last_error=checkpoint.last_error,
    )


def _provider_phase(value: str, field_name: str) -> str:
    return _require_text(value, field_name).lower()


def _ticker(value: str) -> str:
    return _require_text(value, "ticker").upper()


def _period_key(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def _period_value(value: str | None) -> str | None:
    text = _period_key(value)
    return text or None


def _require_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text
