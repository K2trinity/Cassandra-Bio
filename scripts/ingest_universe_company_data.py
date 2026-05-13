from __future__ import annotations

import argparse
import csv
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
from src.backtest.universe_catalog import write_universe_snapshot
from src.backtest.universe_builder import (
    BIOTECH_US_UNIVERSE_ID,
    UniverseSourceRow,
    build_universe_snapshot,
)
from src.data_ingestion.nasdaq_trader import (
    fetch_symbol_directory_texts,
    parse_symbol_directories,
)
from src.data_ingestion.download_executor import DownloadRequest, run_download
from src.data_ingestion.rate_limit import FixedWindowRateLimit

SUPPORTED_PROVIDERS = {"sec", "tiingo", "fmp"}
SAFE_PARTITION_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
REQUIRED_UNIVERSE_EXPANSION_COLUMNS = {
    "ticker",
    "company_name",
    "exchange",
    "asset_type",
}
CURATED_EXPANSION_SOURCE = "curated_universe_expansion"
NASDAQ_KEYWORD_EXPANSION_SOURCE = "nasdaq_trader_keyword"
DEFAULT_BIOTECH_NAME_KEYWORDS = (
    "biotech",
    "bioworks",
    "biopharma",
    "biotherapeutics",
    "bioscience",
    "biosciences",
    "genetic",
    "genetics",
    "genomics",
    "oncology",
    "pharmaceutical",
    "pharmaceuticals",
    "therapeutic",
    "therapeutics",
)
COMMON_SECURITY_NAME_SUFFIXES = (
    "American Depositary Shares",
    "Class A Common Stock",
    "Class B Common Stock",
    "Common Shares",
    "Common Stock",
    "Ordinary Shares",
)


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
    parser.add_argument("--universe-expansion-csv", action="append", default=[])
    parser.add_argument("--expand-from-nasdaq-trader", action="store_true")
    parser.add_argument("--nasdaq-expansion-keywords")
    parser.add_argument("--max-expansion-tickers", type=int)
    parser.add_argument("--write-universe-only", action="store_true")
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
    base_rows = load_latest_universe_source_rows(
        db_path=db_path,
        universe_id=args.universe_id,
        snapshot_date=args.snapshot_date,
    )
    expansion_rows = load_universe_expansion_rows(args)
    rows, expansion_summary = merge_universe_source_rows(
        base_rows,
        expansion_rows,
        snapshot_date=args.snapshot_date,
    )
    selected_tickers = _selected_tickers(
        rows,
        include_tickers=_parse_optional_tickers(args.include_tickers),
        limit_tickers=args.limit_tickers,
        snapshot_date=args.snapshot_date,
    )

    batch_summaries = []
    universe_write = {"status": "not_requested"}
    if args.write_universe_only:
        universe_write = write_current_universe_snapshot(
            rows,
            db_path=db_path,
            snapshot_date=args.snapshot_date,
            dry_run=args.dry_run,
        )
    else:
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
    if args.align_events and args.write_universe_only:
        alignment = {"status": "skipped", "reason": "write_universe_only"}
    elif args.align_events:
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
        "base_universe_rows": len(base_rows),
        "universe_rows": len(rows),
        "universe_expansion": expansion_summary,
        "universe_write": universe_write,
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


def load_universe_expansion_rows(args: argparse.Namespace) -> list[UniverseSourceRow]:
    rows: list[UniverseSourceRow] = []
    for csv_path in args.universe_expansion_csv:
        rows.extend(read_universe_expansion_csv(csv_path))
    if args.expand_from_nasdaq_trader:
        rows.extend(
            load_nasdaq_trader_keyword_expansion_rows(
                keywords=_parse_optional_keywords(args.nasdaq_expansion_keywords),
                max_tickers=args.max_expansion_tickers,
            )
        )
    elif args.max_expansion_tickers is not None:
        raise ValueError(
            "max_expansion_tickers requires --expand-from-nasdaq-trader"
        )
    return rows


def read_universe_expansion_csv(path: str | Path) -> list[UniverseSourceRow]:
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_UNIVERSE_EXPANSION_COLUMNS - fieldnames)
        if missing_columns:
            raise ValueError(
                "universe expansion CSV missing required columns: "
                f"{', '.join(missing_columns)}"
            )

        rows: list[UniverseSourceRow] = []
        for row_number, row in enumerate(reader, start=2):
            values = {
                key: (row.get(key) or "").strip()
                for key in REQUIRED_UNIVERSE_EXPANSION_COLUMNS
            }
            missing_values = sorted(key for key, value in values.items() if not value)
            if missing_values:
                raise ValueError(
                    "universe expansion CSV row "
                    f"{row_number} missing required values: "
                    f"{', '.join(missing_values)}"
                )
            rows.append(
                UniverseSourceRow(
                    ticker=values["ticker"],
                    company_name=values["company_name"],
                    exchange=values["exchange"],
                    asset_type=values["asset_type"],
                    source=(row.get("source") or "").strip() or CURATED_EXPANSION_SOURCE,
                    source_weight=_optional_float(row.get("source_weight")),
                    industry=(row.get("industry") or "").strip() or None,
                    cik=(row.get("cik") or "").strip() or None,
                    cusip=(row.get("cusip") or "").strip() or None,
                    isin=(row.get("isin") or "").strip() or None,
                )
            )
        return rows


def load_nasdaq_trader_keyword_expansion_rows(
    *,
    keywords: tuple[str, ...] | None = None,
    max_tickers: int | None = None,
    nasdaq_fetcher=None,
) -> list[UniverseSourceRow]:
    if max_tickers is not None and max_tickers < 0:
        raise ValueError("max_expansion_tickers must be non-negative")
    if nasdaq_fetcher is None:
        nasdaq_fetcher = lambda: fetch_symbol_directory_texts(
            rate_limiter=FixedWindowRateLimit(max_requests=1, window_seconds=1.0)
        )

    results = tuple(nasdaq_fetcher())
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
        raise RuntimeError(f"Nasdaq Trader universe expansion fetch incomplete: {details}")

    texts = {result.endpoint: result.payload for result in results}
    missing = sorted({"nasdaqlisted", "otherlisted"} - set(texts))
    if missing:
        raise RuntimeError(
            "Nasdaq Trader universe expansion fetch incomplete: missing "
            f"{', '.join(missing)}"
        )

    candidate_rows = parse_symbol_directories(
        nasdaqlisted_text=texts["nasdaqlisted"] or "",
        otherlisted_text=texts["otherlisted"] or "",
    )
    keyword_tuple = keywords or DEFAULT_BIOTECH_NAME_KEYWORDS
    matched = [
        UniverseSourceRow(
            ticker=row.ticker,
            company_name=_clean_security_name(row.company_name),
            exchange=row.exchange,
            asset_type=row.asset_type,
            source=NASDAQ_KEYWORD_EXPANSION_SOURCE,
            industry="Biotechnology",
        )
        for row in candidate_rows
        if _matches_any_keyword(row.company_name, keyword_tuple)
    ]
    deduped = _dedupe_rows_by_ticker(matched)
    if max_tickers is not None:
        return deduped[:max_tickers]
    return deduped


def merge_universe_source_rows(
    base_rows: list[UniverseSourceRow],
    expansion_rows: list[UniverseSourceRow],
    *,
    snapshot_date: str,
) -> tuple[list[UniverseSourceRow], dict[str, Any]]:
    if not expansion_rows:
        base_snapshot = build_universe_snapshot(base_rows, as_of_date=snapshot_date)
        return list(base_rows), {
            "status": "disabled",
            "source_rows": 0,
            "accepted_source_rows": 0,
            "duplicate_source_rows": 0,
            "base_member_count": len(base_snapshot.members),
            "expanded_member_count": len(base_snapshot.members),
            "added_member_count": 0,
            "added_tickers": [],
        }

    base_snapshot = build_universe_snapshot(base_rows, as_of_date=snapshot_date)
    base_tickers = {member.ticker for member in base_snapshot.members}
    seen = {_source_row_key(row) for row in base_rows}
    merged_rows = list(base_rows)
    duplicate_source_rows = 0
    for row in expansion_rows:
        key = _source_row_key(row)
        if key in seen:
            duplicate_source_rows += 1
            continue
        seen.add(key)
        merged_rows.append(row)

    expanded_snapshot = build_universe_snapshot(merged_rows, as_of_date=snapshot_date)
    expanded_tickers = {member.ticker for member in expanded_snapshot.members}
    added_tickers = sorted(expanded_tickers - base_tickers)
    return merged_rows, {
        "status": "applied",
        "source_rows": len(expansion_rows),
        "accepted_source_rows": len(expansion_rows) - duplicate_source_rows,
        "duplicate_source_rows": duplicate_source_rows,
        "base_member_count": len(base_snapshot.members),
        "expanded_member_count": len(expanded_snapshot.members),
        "added_member_count": len(added_tickers),
        "added_tickers": added_tickers,
    }


def write_current_universe_snapshot(
    rows: list[UniverseSourceRow],
    *,
    db_path: str | Path,
    snapshot_date: str,
    dry_run: bool,
) -> dict[str, Any]:
    snapshot = build_universe_snapshot(rows, as_of_date=snapshot_date)
    if dry_run:
        return {
            "status": "dry_run",
            "universe_snapshot_id": snapshot.universe_snapshot_id,
            "member_count": len(snapshot.members),
        }
    write_universe_snapshot(snapshot, db_path=db_path)
    return {
        "status": "written",
        "universe_snapshot_id": snapshot.universe_snapshot_id,
        "member_count": len(snapshot.members),
    }


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


def _parse_optional_keywords(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    keywords = tuple(keyword.strip().lower() for keyword in value.split(",") if keyword.strip())
    return keywords or None


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


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


def _source_row_key(row: UniverseSourceRow) -> tuple[Any, ...]:
    return (
        _normalize_ticker(row.ticker),
        row.company_name.strip(),
        row.exchange.strip().upper(),
        row.asset_type.strip().lower().replace("-", " "),
        row.source.strip().lower(),
        row.source_weight,
        row.industry,
        row.cik,
        row.cusip,
        row.isin,
    )


def _matches_any_keyword(value: str, keywords: tuple[str, ...]) -> bool:
    normalized = value.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _dedupe_rows_by_ticker(rows: list[UniverseSourceRow]) -> list[UniverseSourceRow]:
    deduped: dict[str, UniverseSourceRow] = {}
    for row in sorted(rows, key=lambda candidate: _normalize_ticker(candidate.ticker)):
        deduped.setdefault(_normalize_ticker(row.ticker), row)
    return list(deduped.values())


def _clean_security_name(value: str) -> str:
    cleaned = value.strip()
    for suffix in COMMON_SECURITY_NAME_SUFFIXES:
        pattern = re.compile(rf"\s*-?\s*{re.escape(suffix)}\s*$", flags=re.IGNORECASE)
        cleaned = pattern.sub("", cleaned).strip()
    return cleaned or value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
