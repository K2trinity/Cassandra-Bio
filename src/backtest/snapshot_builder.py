from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


_CANONICAL_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SnapshotMetadataError(ValueError):
    """Raised when snapshot metadata does not match its auditable identity."""


@dataclass(frozen=True)
class DataSnapshot:
    data_snapshot_id: str
    snapshot_date: str | date | datetime
    price_source: str
    event_source_db: str
    universe_id: str
    bias_profile: str
    price_partition_root: str
    event_snapshot_hash: str
    security_master_hash: str
    coverage: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_date", _canonical_snapshot_date(self.snapshot_date)
        )
        object.__setattr__(self, "coverage", MappingProxyType(dict(self.coverage)))


def _canonical_snapshot_date(snapshot_date: str | date | datetime) -> str:
    if isinstance(snapshot_date, datetime):
        return snapshot_date.date().isoformat()
    if isinstance(snapshot_date, date):
        return snapshot_date.isoformat()
    if isinstance(snapshot_date, str):
        if not _CANONICAL_DATE_RE.fullmatch(snapshot_date):
            raise ValueError(
                "snapshot_date string must use canonical YYYY-MM-DD format"
            )
        try:
            return date.fromisoformat(snapshot_date).isoformat()
        except ValueError as exc:
            raise ValueError(f"invalid snapshot_date: {snapshot_date!r}") from exc
    raise ValueError("snapshot_date must be a YYYY-MM-DD string, date, or datetime")


def _canonical_json(value: Any) -> str:
    if isinstance(value, Mapping):
        value = dict(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def build_data_snapshot_id(
    *,
    snapshot_date: str | date | datetime,
    price_source: str,
    universe_id: str,
    security_master_hash: str,
    event_snapshot_hash: str,
) -> str:
    canonical_date = _canonical_snapshot_date(snapshot_date)
    payload = {
        "event_snapshot_hash": event_snapshot_hash,
        "price_source": price_source,
        "security_master_hash": security_master_hash,
        "snapshot_date": canonical_date,
        "universe_id": universe_id,
    }
    digest = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    date_token = canonical_date.replace("-", "")
    return f"snap_{date_token}_{digest}"


def _expected_snapshot_id(snapshot: DataSnapshot) -> str:
    return build_data_snapshot_id(
        snapshot_date=snapshot.snapshot_date,
        price_source=snapshot.price_source,
        universe_id=snapshot.universe_id,
        security_master_hash=snapshot.security_master_hash,
        event_snapshot_hash=snapshot.event_snapshot_hash,
    )


def _canonical_snapshot_metadata(
    snapshot: DataSnapshot, coverage_json: str
) -> dict[str, str]:
    return {
        "data_snapshot_id": snapshot.data_snapshot_id,
        "snapshot_date": _canonical_snapshot_date(snapshot.snapshot_date),
        "price_source": snapshot.price_source,
        "event_source_db": snapshot.event_source_db,
        "universe_id": snapshot.universe_id,
        "bias_profile": snapshot.bias_profile,
        "price_partition_root": snapshot.price_partition_root,
        "event_snapshot_hash": snapshot.event_snapshot_hash,
        "security_master_hash": snapshot.security_master_hash,
        "coverage_json": coverage_json,
    }


def _metadata_from_row(row: tuple[Any, ...]) -> dict[str, str]:
    return {
        "data_snapshot_id": row[0],
        "snapshot_date": _canonical_snapshot_date(row[1]),
        "price_source": row[2],
        "event_source_db": row[3],
        "universe_id": row[4],
        "bias_profile": row[5],
        "price_partition_root": row[6],
        "event_snapshot_hash": row[7],
        "security_master_hash": row[8],
        "coverage_json": row[9],
    }


def insert_data_snapshot(
    snapshot: DataSnapshot, *, db_path: str | Path | None = None
) -> None:
    expected_id = _expected_snapshot_id(snapshot)
    if snapshot.data_snapshot_id != expected_id:
        raise SnapshotMetadataError(
            f"data_snapshot_id {snapshot.data_snapshot_id!r} does not match "
            f"expected {expected_id!r}"
        )

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    coverage_json = _canonical_json(snapshot.coverage)
    metadata = _canonical_snapshot_metadata(snapshot, coverage_json)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        existing = conn.execute(
            """
            SELECT
                data_snapshot_id,
                snapshot_date,
                price_source,
                event_source_db,
                universe_id,
                bias_profile,
                price_partition_root,
                event_snapshot_hash,
                security_master_hash,
                coverage_json
            FROM data_snapshots
            WHERE data_snapshot_id = ?
            """,
            [snapshot.data_snapshot_id],
        ).fetchone()
        if existing is not None:
            if _metadata_from_row(existing) == metadata:
                return
            raise SnapshotMetadataError(
                f"data_snapshot_id {snapshot.data_snapshot_id!r} already exists "
                "with different metadata"
            )

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
                metadata["data_snapshot_id"],
                metadata["snapshot_date"],
                metadata["price_source"],
                metadata["event_source_db"],
                metadata["universe_id"],
                metadata["bias_profile"],
                metadata["price_partition_root"],
                metadata["event_snapshot_hash"],
                metadata["security_master_hash"],
                metadata["coverage_json"],
            ],
        )
    finally:
        conn.close()
