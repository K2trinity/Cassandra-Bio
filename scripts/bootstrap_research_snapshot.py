from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.data_loader import DATA_DIR
from src.backtest.data_sources import YFINANCE_PROFILE
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


def bootstrap_snapshot(
    *,
    ohlc_dir: str | Path = DATA_DIR,
    research_dir: str | Path = RESEARCH_DIR,
    db_path: str | Path | None = None,
    event_db_path: str | Path = EVENTS_DB_PATH,
    snapshot_date: str,
    universe_id: str,
) -> dict:
    research_root = Path(research_dir)
    resolved_db_path = (
        Path(db_path) if db_path is not None else research_root / RESEARCH_DB_PATH.name
    )
    resolved_event_db_path = Path(event_db_path)
    price_root = research_root / "prices_daily"
    security_master_hash = "local-yfinance-security-master-v1"
    event_snapshot_hash = "events-db-current"
    snapshot_id = build_data_snapshot_id(
        snapshot_date=snapshot_date,
        price_source=YFINANCE_PROFILE.source_id,
        universe_id=universe_id,
        security_master_hash=security_master_hash,
        event_snapshot_hash=event_snapshot_hash,
    )

    apply_sqlite_migrations(resolved_event_db_path)
    initialize_research_database(resolved_db_path)
    coverage = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=price_root,
        data_snapshot_id=snapshot_id,
        source=YFINANCE_PROFILE.source_id,
    )
    insert_data_snapshot(
        DataSnapshot(
            data_snapshot_id=snapshot_id,
            snapshot_date=snapshot_date,
            price_source=YFINANCE_PROFILE.source_id,
            event_source_db=str(resolved_event_db_path),
            universe_id=universe_id,
            bias_profile=YFINANCE_PROFILE.bias_profile.value,
            price_partition_root=str(price_root),
            event_snapshot_hash=event_snapshot_hash,
            security_master_hash=security_master_hash,
            coverage=coverage,
        ),
        db_path=resolved_db_path,
    )
    return {"data_snapshot_id": snapshot_id, "coverage": coverage}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--universe-id", default="biotech_four_v1")
    args = parser.parse_args()
    result = bootstrap_snapshot(
        snapshot_date=args.snapshot_date,
        universe_id=args.universe_id,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
