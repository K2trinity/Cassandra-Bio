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

SUPPORTED_PROVIDERS = {"nasdaq", "nasdaq_trader", "sec", "tiingo", "fmp"}
REQUIRED_EXCHANGE_LISTING_COLUMNS = {
    "ticker",
    "company_name",
    "exchange",
    "asset_type",
}


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
    try:
        if not args.exchange_listings_csv:
            raise ValueError(
                "--exchange-listings-csv is required until live Nasdaq universe "
                "loading is implemented."
            )
        providers = _parse_providers(args.providers)
        rows = _read_exchange_listing_fixture(args.exchange_listings_csv)
        request = DownloadRequest(
            snapshot_date=args.snapshot_date,
            start_date=args.start_date,
            end_date=args.end_date,
            providers=providers,
            dry_run=args.dry_run,
            resume=args.resume,
            limit_tickers=args.limit_tickers,
            universe_id=args.universe_id,
            research_dir=args.research_dir,
            daily_fmp_budget=args.daily_fmp_budget,
        )
        summary = run_download(request, universe_rows=rows)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(summary), sort_keys=True, indent=2))
    return 0


def _parse_providers(value: str) -> tuple[str, ...]:
    providers = tuple(
        provider.strip().lower() for provider in value.split(",") if provider.strip()
    )
    if not providers:
        raise ValueError("at least one provider must be specified")
    unsupported = sorted(set(providers) - SUPPORTED_PROVIDERS)
    if unsupported:
        raise ValueError(f"unsupported provider: {', '.join(unsupported)}")
    return providers


def _read_exchange_listing_fixture(path: str | None) -> list[UniverseSourceRow] | None:
    if not path:
        return None
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_EXCHANGE_LISTING_COLUMNS - fieldnames)
        if missing_columns:
            raise ValueError(
                "exchange listing CSV missing required columns: "
                f"{', '.join(missing_columns)}"
            )

        rows: list[UniverseSourceRow] = []
        for row_number, row in enumerate(reader, start=2):
            values = {
                key: (row.get(key) or "").strip()
                for key in REQUIRED_EXCHANGE_LISTING_COLUMNS
            }
            missing_values = sorted(key for key, value in values.items() if not value)
            if missing_values:
                raise ValueError(
                    "exchange listing CSV row "
                    f"{row_number} missing required values: "
                    f"{', '.join(missing_values)}"
                )
            rows.append(
                UniverseSourceRow(
                    ticker=values["ticker"],
                    company_name=values["company_name"],
                    exchange=values["exchange"],
                    asset_type=values["asset_type"],
                    source="exchange_listings",
                    industry=(row.get("industry") or "").strip() or None,
                    cik=(row.get("cik") or "").strip() or None,
                )
            )
        return rows


if __name__ == "__main__":
    raise SystemExit(main())
