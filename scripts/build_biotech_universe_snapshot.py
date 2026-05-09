from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.research_db import RESEARCH_DB_PATH
from src.backtest.universe_catalog import write_universe_snapshot
from src.backtest.universe_builder import (
    UniverseSourceRow,
    build_universe_snapshot,
)

ALLOWED_UNIVERSE_SNAPSHOT_SOURCES = frozenset({"xbi", "ibb", "exchange_listings"})


def build_snapshot_from_csvs(
    *,
    xbi_holdings: str | Path,
    ibb_holdings: str | Path,
    exchange_listings: str | Path,
    db_path: str | Path | None = None,
    as_of_date: str,
) -> dict[str, object]:
    rows = [
        *_read_rows(xbi_holdings, source="xbi"),
        *_read_rows(ibb_holdings, source="ibb"),
        *_read_rows(exchange_listings, source="exchange_listings"),
    ]
    snapshot = build_universe_snapshot(rows, as_of_date=as_of_date)
    write_universe_snapshot(snapshot, db_path=db_path or RESEARCH_DB_PATH)
    return {
        "universe_snapshot_id": snapshot.universe_snapshot_id,
        "universe_id": snapshot.universe_id,
        "as_of_date": snapshot.as_of_date,
        "member_count": len(snapshot.members),
        "benchmark_tickers": list(snapshot.benchmark_tickers),
        "bias_status": snapshot.bias_status,
        "survivorship_bias_warning": snapshot.survivorship_bias_warning,
    }


def _read_rows(path: str | Path, *, source: str) -> list[UniverseSourceRow]:
    normalized_source = _normalize_source(source)
    with Path(path).open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [
            UniverseSourceRow(
                ticker=_required_field(row, "ticker"),
                company_name=_required_field(row, "company_name"),
                exchange=_required_field(row, "exchange"),
                asset_type=_required_field(row, "asset_type"),
                source=normalized_source,
                source_weight=_optional_float(row.get("source_weight")),
                industry=_optional_text(row.get("industry")),
                cik=_optional_text(row.get("cik")),
                cusip=_optional_text(row.get("cusip")),
                isin=_optional_text(row.get("isin")),
            )
            for row in reader
        ]


def _normalize_source(source: str) -> str:
    normalized = source.strip().lower()
    if normalized not in ALLOWED_UNIVERSE_SNAPSHOT_SOURCES:
        raise ValueError(f"Unsupported universe source: {normalized}")
    return normalized


def _required_field(row: dict[str, str], field_name: str) -> str:
    value = row.get(field_name)
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: str | None) -> float | None:
    stripped = _optional_text(value)
    if stripped is None:
        return None
    return float(stripped)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xbi-holdings", required=True)
    parser.add_argument("--ibb-holdings", required=True)
    parser.add_argument("--exchange-listings", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--db-path", default=str(RESEARCH_DB_PATH))
    args = parser.parse_args()
    summary = build_snapshot_from_csvs(
        xbi_holdings=args.xbi_holdings,
        ibb_holdings=args.ibb_holdings,
        exchange_listings=args.exchange_listings,
        db_path=args.db_path,
        as_of_date=args.as_of_date,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
