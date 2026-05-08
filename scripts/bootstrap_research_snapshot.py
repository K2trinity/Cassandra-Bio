from __future__ import annotations

import argparse
from hashlib import sha256
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.data_loader import DATA_DIR
from src.backtest.data_sources import TIINGO_PROFILE, YFINANCE_PROFILE, SourceProfile
from src.backtest.events_db import DB_PATH as EVENTS_DB_PATH
from src.backtest.migrations import apply_sqlite_migrations
from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily
from src.backtest.research_db import (
    RESEARCH_DB_PATH,
    RESEARCH_DIR,
    initialize_research_database,
)
from src.backtest.snapshot_builder import (
    DataSnapshot,
    build_data_snapshot_id,
    insert_data_snapshot,
)
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID

EVENT_HASH_TABLES = (
    "schema_migrations",
    "biotech_events",
    "event_source_documents",
    "event_extraction_runs",
    "event_quality_issues",
)
PRICE_SOURCE_PROFILES = {
    TIINGO_PROFILE.source_id: TIINGO_PROFILE,
    YFINANCE_PROFILE.source_id: YFINANCE_PROFILE,
}


def bootstrap_snapshot(
    *,
    ohlc_dir: str | Path = DATA_DIR,
    research_dir: str | Path = RESEARCH_DIR,
    db_path: str | Path | None = None,
    event_db_path: str | Path = EVENTS_DB_PATH,
    snapshot_date: str,
    universe_id: str = BIOTECH_US_UNIVERSE_ID,
    price_source: str = TIINGO_PROFILE.source_id,
) -> dict:
    profile = _provider_profile(price_source)
    research_root = Path(research_dir)
    resolved_db_path = (
        Path(db_path) if db_path is not None else research_root / RESEARCH_DB_PATH.name
    )
    resolved_event_db_path = Path(event_db_path)
    price_root = research_root / "prices_daily"
    security_master_hash = compute_ohlc_manifest_hash(ohlc_dir)
    apply_sqlite_migrations(resolved_event_db_path)
    event_snapshot_hash = compute_event_source_hash(resolved_event_db_path)
    snapshot_id = build_data_snapshot_id(
        snapshot_date=snapshot_date,
        price_source=profile.source_id,
        universe_id=universe_id,
        security_master_hash=security_master_hash,
        event_snapshot_hash=event_snapshot_hash,
    )

    initialize_research_database(resolved_db_path)
    coverage = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=price_root,
        data_snapshot_id=snapshot_id,
        source=profile.source_id,
    )
    insert_data_snapshot(
        DataSnapshot(
            data_snapshot_id=snapshot_id,
            snapshot_date=snapshot_date,
            price_source=profile.source_id,
            event_source_db=str(resolved_event_db_path),
            universe_id=universe_id,
            bias_profile=profile.bias_profile.value,
            price_partition_root=str(price_root),
            event_snapshot_hash=event_snapshot_hash,
            security_master_hash=security_master_hash,
            coverage=coverage,
        ),
        db_path=resolved_db_path,
    )
    return {"data_snapshot_id": snapshot_id, "coverage": coverage}


def _provider_profile(price_source: str) -> SourceProfile:
    try:
        return PRICE_SOURCE_PROFILES[price_source]
    except KeyError as exc:
        raise ValueError(f"unsupported price source: {price_source}") from exc


def compute_ohlc_manifest_hash(ohlc_dir: str | Path) -> str:
    input_dir = Path(ohlc_dir)
    manifest = {
        "format": "local_ohlc_manifest_v1",
        "files": [
            {
                "filename": path.name,
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(input_dir.glob("*.parquet"))
        ],
    }
    return _canonical_hash(manifest)


def compute_event_source_hash(event_db_path: str | Path) -> str:
    conn = sqlite3.connect(Path(event_db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            table_name: _event_table_manifest(conn, table_name)
            for table_name in EVENT_HASH_TABLES
            if _sqlite_table_exists(conn, table_name)
        }
    finally:
        conn.close()
    return _canonical_hash({"format": "local_event_source_v1", "tables": tables})


def _event_table_manifest(
    conn: sqlite3.Connection,
    table_name: str,
) -> dict[str, object]:
    columns = [
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({_quote_identifier(table_name)})"
        ).fetchall()
    ]
    included_columns = (
        ["migration_id"] if table_name == "schema_migrations" else columns
    )
    column_sql = ", ".join(_quote_identifier(column) for column in included_columns)
    rows = [
        {column: _json_ready(row[column]) for column in included_columns}
        for row in conn.execute(
            f"SELECT {column_sql} FROM {_quote_identifier(table_name)}"
        )
    ]
    return {
        "columns": included_columns,
        "rows": sorted(rows, key=_canonical_json),
    }


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        is not None
    )


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "bytes_sha256": sha256(value).hexdigest(),
            "size_bytes": len(value),
        }
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--universe-id", default=BIOTECH_US_UNIVERSE_ID)
    parser.add_argument(
        "--price-source",
        default=TIINGO_PROFILE.source_id,
        choices=sorted(PRICE_SOURCE_PROFILES),
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    result = bootstrap_snapshot(
        snapshot_date=args.snapshot_date,
        universe_id=args.universe_id,
        price_source=args.price_source,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
