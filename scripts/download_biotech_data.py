from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.research_db import RESEARCH_DIR
from src.backtest.universe_builder import UniverseSourceRow
from src.data_ingestion.download_executor import DownloadRequest, run_download


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--universe-id", default="biotech_us_v1")
    parser.add_argument("--providers", default="nasdaq,sec,tiingo,fmp")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit-tickers", type=int)
    parser.add_argument("--daily-fmp-budget", type=int, default=240)
    parser.add_argument("--research-dir", default=str(RESEARCH_DIR))
    parser.add_argument("--exchange-listings-csv")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    rows = _read_exchange_listing_fixture(args.exchange_listings_csv)
    request = DownloadRequest(
        snapshot_date=args.snapshot_date,
        start_date=args.start_date,
        end_date=args.end_date,
        providers=_parse_providers(args.providers),
        dry_run=args.dry_run,
        resume=args.resume,
        limit_tickers=args.limit_tickers,
        universe_id=args.universe_id,
        research_dir=args.research_dir,
        daily_fmp_budget=args.daily_fmp_budget,
    )
    summary = run_download(request, universe_rows=rows)
    print(json.dumps(asdict(summary), sort_keys=True, indent=2))
    return 0


def _parse_providers(value: str) -> tuple[str, ...]:
    return tuple(
        provider.strip().lower() for provider in value.split(",") if provider.strip()
    )


def _read_exchange_listing_fixture(path: str | None) -> list[UniverseSourceRow] | None:
    if not path:
        return None
    with Path(path).open(newline="", encoding="utf-8") as file:
        return [
            UniverseSourceRow(
                ticker=row["ticker"],
                company_name=row["company_name"],
                exchange=row["exchange"],
                asset_type=row["asset_type"],
                source="exchange_listings",
                industry=row.get("industry") or None,
                cik=row.get("cik") or None,
            )
            for row in csv.DictReader(file)
        ]


if __name__ == "__main__":
    raise SystemExit(main())
