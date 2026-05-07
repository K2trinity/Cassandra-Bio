from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


@dataclass(frozen=True)
class DataSnapshot:
    data_snapshot_id: str
    snapshot_date: str
    price_source: str
    event_source_db: str
    universe_id: str
    bias_profile: str
    price_partition_root: str
    event_snapshot_hash: str
    security_master_hash: str
    coverage: dict[str, Any]


def build_data_snapshot_id(
    *,
    snapshot_date: str,
    price_source: str,
    universe_id: str,
    security_master_hash: str,
    event_snapshot_hash: str,
) -> str:
    payload = {
        "event_snapshot_hash": event_snapshot_hash,
        "price_source": price_source,
        "security_master_hash": security_master_hash,
        "snapshot_date": snapshot_date,
        "universe_id": universe_id,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    date_token = snapshot_date.replace("-", "")
    return f"snap_{date_token}_{digest}"


def insert_data_snapshot(
    snapshot: DataSnapshot, *, db_path: str | Path | None = None
) -> None:
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    coverage_json = json.dumps(snapshot.coverage, sort_keys=True)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            """
            INSERT INTO data_snapshots (
                data_snapshot_id,
                snapshot_date,
                price_source,
                event_source_db,
                universe_id,
                bias_profile,
                price_partition_root,
                event_snapshot_hash,
                security_master_hash,
                coverage_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                snapshot.data_snapshot_id,
                snapshot.snapshot_date,
                snapshot.price_source,
                snapshot.event_source_db,
                snapshot.universe_id,
                snapshot.bias_profile,
                snapshot.price_partition_root,
                snapshot.event_snapshot_hash,
                snapshot.security_master_hash,
                coverage_json,
            ],
        )
    finally:
        conn.close()
