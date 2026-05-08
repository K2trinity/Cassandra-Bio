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
from src.data_ingestion.nasdaq_trader import (
    fetch_symbol_directory_texts,
    parse_symbol_directories,
)
from src.data_ingestion.provider_log import record_provider_fetch
from src.data_ingestion.rate_limit import FixedWindowRateLimit

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
        providers = _parse_providers(args.providers)
        rows = _load_universe_rows(
            args.exchange_listings_csv,
            db_path=Path(args.research_dir) / "cassandra_research.duckdb",
        )
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


def _load_universe_rows(
    exchange_listings_csv: str | None,
    *,
    db_path: str | Path | None = None,
    nasdaq_fetcher=None,
) -> list[UniverseSourceRow] | None:
    if exchange_listings_csv:
        return _read_exchange_listing_fixture(exchange_listings_csv)

    if nasdaq_fetcher is None:
        nasdaq_fetcher = lambda: fetch_symbol_directory_texts(
            rate_limiter=FixedWindowRateLimit(max_requests=1, window_seconds=1.0)
        )
    results = tuple(nasdaq_fetcher())
    if db_path is not None:
        _record_nasdaq_fetch_results(results, db_path=db_path)
    failed = [
        result
        for result in results
        if result.status != "success" or not result.payload
    ]
    if failed:
        details = "; ".join(
            f"{result.endpoint}: {result.status}"
            + (f" ({result.message})" if result.message else "")
            for result in failed
        )
        raise RuntimeError(f"Nasdaq Trader universe fetch incomplete: {details}")

    texts = {result.endpoint: result.payload for result in results}
    missing = sorted({"nasdaqlisted", "otherlisted"} - set(texts))
    if missing:
        raise RuntimeError(
            "Nasdaq Trader universe fetch incomplete: missing "
            f"{', '.join(missing)}"
        )

    return parse_symbol_directories(
        nasdaqlisted_text=texts["nasdaqlisted"] or "",
        otherlisted_text=texts["otherlisted"] or "",
    )


def _record_nasdaq_fetch_results(results, *, db_path: str | Path) -> None:
    for result in results:
        metadata = {"endpoint": result.endpoint}
        if result.retry_after_seconds is not None:
            metadata["retry_after_seconds"] = result.retry_after_seconds
        record_provider_fetch(
            provider=result.provider,
            endpoint=result.endpoint,
            request_hash=result.request_hash,
            status=result.status,
            message=result.message,
            metadata=metadata,
            db_path=db_path,
        )


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
