from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from src.backtest.event_alignment import (
    align_events_for_snapshot,
    write_event_price_links,
)
from src.backtest.price_snapshot import load_prices_daily_ohlc
from src.backtest.research_db import RESEARCH_DIR, initialize_research_database
from src.backtest.universe_builder import (
    BIOTECH_US_UNIVERSE_ID,
    UniverseSourceRow,
    build_universe_snapshot,
)
from src.data_ingestion.download_executor import DownloadRequest, run_download

SUPPORTED_PROVIDERS = {"sec", "tiingo", "fmp"}
SAFE_PARTITION_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--providers", default="tiingo,sec,fmp")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-tickers", type=int)
    parser.add_argument("--include-tickers")
    parser.add_argument("--daily-fmp-budget", type=int, default=240)
    parser.add_argument("--max-provider-attempts", type=int, default=3)
    parser.add_argument("--max-retry-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--research-dir", default=str(RESEARCH_DIR))
    parser.add_argument("--universe-id", default=BIOTECH_US_UNIVERSE_ID)
    parser.add_argument("--align-events", action="store_true")
    parser.add_argument("--replace-event-links", action="store_true")
    parser.add_argument("--events-db", default=str(ROOT_DIR / "data" / "events.db"))
    parser.add_argument("--event-links-root")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        summary = ingest_universe_company_data(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def ingest_universe_company_data(args: argparse.Namespace) -> dict[str, Any]:
    providers = _parse_providers(args.providers)
    if args.batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    research_dir = Path(args.research_dir)
    db_path = initialize_research_database(research_dir / "cassandra_research.duckdb")
    rows = load_latest_universe_source_rows(
        db_path=db_path,
        universe_id=args.universe_id,
        snapshot_date=args.snapshot_date,
    )
    selected_tickers = _selected_tickers(
        rows,
        include_tickers=_parse_optional_tickers(args.include_tickers),
        limit_tickers=args.limit_tickers,
        snapshot_date=args.snapshot_date,
    )

    batch_summaries = []
    for batch in _chunks(selected_tickers, args.batch_size):
        request = DownloadRequest(
            snapshot_date=args.snapshot_date,
            start_date=args.start_date,
            end_date=args.end_date,
            providers=providers,
            dry_run=args.dry_run,
            resume=args.resume,
            include_tickers=tuple(batch),
            universe_id=args.universe_id,
            research_dir=research_dir,
            daily_fmp_budget=args.daily_fmp_budget,
            max_provider_attempts=args.max_provider_attempts,
            max_retry_sleep_seconds=args.max_retry_sleep_seconds,
        )
        batch_summaries.append(asdict(run_download(request, universe_rows=rows)))

    alignment = {"status": "not_requested"}
    if args.align_events:
        data_snapshot_id = (
            batch_summaries[0]["data_snapshot_id"] if batch_summaries else None
        )
        if data_snapshot_id is None:
            alignment = {"status": "skipped", "reason": "no_selected_tickers"}
        else:
            alignment = align_trusted_events_for_snapshot(
                tickers=selected_tickers,
                data_snapshot_id=data_snapshot_id,
                start_date=args.start_date,
                end_date=args.end_date,
                research_dir=research_dir,
                events_db=Path(args.events_db),
                output_root=(
                    Path(args.event_links_root)
                    if args.event_links_root
                    else research_dir / "event_price_links"
                ),
                replace=args.replace_event_links,
            )

    return {
        "snapshot_date": args.snapshot_date,
        "providers": providers,
        "universe_rows": len(rows),
        "selected_tickers": selected_tickers,
        "batch_size": args.batch_size,
        "batches": batch_summaries,
        "alignment": alignment,
    }


def load_latest_universe_source_rows(
    *,
    db_path: str | Path,
    universe_id: str,
    snapshot_date: str,
) -> list[UniverseSourceRow]:
    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT source_payload_json
            FROM universe_snapshots
            WHERE universe_id = ?
              AND as_of_date <= CAST(? AS DATE)
            ORDER BY as_of_date DESC, created_at DESC
            LIMIT 1
            """,
            [universe_id, snapshot_date],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RuntimeError(
            f"No universe snapshot found for {universe_id} on or before {snapshot_date}"
        )
    payloads = json.loads(row[0])
    return [_source_row_from_payload(payload) for payload in payloads]


def align_trusted_events_for_snapshot(
    *,
    tickers: list[str],
    data_snapshot_id: str,
    start_date: str,
    end_date: str,
    research_dir: Path,
    events_db: Path,
    output_root: Path,
    replace: bool,
) -> dict[str, Any]:
    partition = output_root / f"data_snapshot_id={_safe_partition_token(data_snapshot_id)}"
    existing = partition / "event_price_links.parquet"
    if existing.exists() and not replace:
        return {"status": "skipped", "reason": "event_links_exist", "path": str(existing)}
    if replace and partition.exists():
        shutil.rmtree(partition)

    links = []
    for ticker in tickers:
        events = _trusted_events_frame(
            ticker,
            start_date=start_date,
            end_date=end_date,
            events_db=events_db,
        )
        if events.empty:
            continue
        prices = load_prices_daily_ohlc(
            ticker,
            data_snapshot_id=data_snapshot_id,
            output_root=research_dir / "prices_daily",
            source="tiingo",
        )
        if prices.empty:
            continue
        links.append(
            align_events_for_snapshot(
                events,
                prices,
                data_snapshot_id=data_snapshot_id,
                security_id=f"TIINGO:{ticker}",
            )
        )

    if not links:
        return {"status": "skipped", "reason": "no_event_price_links", "rows": 0}
    frame = pd.concat(links, ignore_index=True)
    path = write_event_price_links(frame, output_root=output_root)
    return {"status": "written", "path": str(path), "rows": int(len(frame))}


def _trusted_events_frame(
    ticker: str,
    *,
    start_date: str,
    end_date: str,
    events_db: Path,
) -> pd.DataFrame:
    from src.backtest import events_db as events_db_module

    original_path = events_db_module.DB_PATH
    events_db_module.DB_PATH = events_db
    try:
        return events_db_module.get_trusted_events_for_backtest(
            ticker,
            start_date=start_date,
            end_date=end_date,
        )
    finally:
        events_db_module.DB_PATH = original_path


def _source_row_from_payload(payload: dict[str, Any]) -> UniverseSourceRow:
    return UniverseSourceRow(
        ticker=str(payload.get("ticker") or ""),
        company_name=str(payload.get("company_name") or ""),
        exchange=str(payload.get("exchange") or ""),
        asset_type=str(payload.get("asset_type") or ""),
        source=str(payload.get("source") or "exchange_listings"),
        source_weight=payload.get("source_weight"),
        industry=payload.get("industry"),
        cik=payload.get("cik"),
        cusip=payload.get("cusip"),
        isin=payload.get("isin"),
    )


def _selected_tickers(
    rows: list[UniverseSourceRow],
    *,
    include_tickers: tuple[str, ...] | None,
    limit_tickers: int | None,
    snapshot_date: str,
) -> list[str]:
    members = build_universe_snapshot(rows, as_of_date=snapshot_date).members
    tickers = [member.ticker for member in members]
    if include_tickers is not None:
        included = set(include_tickers)
        tickers = [ticker for ticker in tickers if ticker in included]
    if limit_tickers is not None:
        if limit_tickers < 0:
            raise ValueError("limit_tickers must be non-negative")
        tickers = tickers[:limit_tickers]
    return tickers


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


def _parse_optional_tickers(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    tickers = tuple(_normalize_ticker(ticker) for ticker in value.split(",") if ticker.strip())
    return tickers or None


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _normalize_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    if not normalized:
        raise ValueError("ticker must be non-empty")
    return normalized


def _safe_partition_token(value: str) -> str:
    if not SAFE_PARTITION_TOKEN.fullmatch(value):
        raise ValueError(f"unsupported data_snapshot_id: {value!r}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
