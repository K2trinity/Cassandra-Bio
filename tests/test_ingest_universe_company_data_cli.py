from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot
from src.backtest.universe_catalog import write_universe_snapshot


def _rows() -> list[UniverseSourceRow]:
    return [
        UniverseSourceRow(
            ticker="MRNA",
            company_name="Moderna, Inc.",
            exchange="NASDAQ",
            asset_type="common_stock",
            source="exchange_listings",
            industry="Biotechnology",
            cik="1682852",
        ),
        UniverseSourceRow(
            ticker="ABBA",
            company_name="ABBA Therapeutics, Inc.",
            exchange="NASDAQ",
            asset_type="common_stock",
            source="exchange_listings",
            industry="Biotechnology",
            cik="0000001",
        ),
        UniverseSourceRow(
            ticker="IBB",
            company_name="iShares Biotechnology ETF",
            exchange="NASDAQ",
            asset_type="etf",
            source="ibb",
        ),
    ]


def _write_snapshot(tmp_path: Path, as_of_date: str = "2026-05-12") -> Path:
    db_path = tmp_path / "cassandra_research.duckdb"
    snapshot = build_universe_snapshot(_rows(), as_of_date=as_of_date)
    write_universe_snapshot(snapshot, db_path=db_path)
    return db_path


def test_load_latest_universe_source_rows_reads_catalog_payload(tmp_path):
    from scripts.ingest_universe_company_data import load_latest_universe_source_rows

    db_path = _write_snapshot(tmp_path)

    rows = load_latest_universe_source_rows(
        db_path=db_path,
        universe_id="biotech_us_v1",
        snapshot_date="2026-05-13",
    )

    assert [row.ticker for row in rows] == ["ABBA", "IBB", "MRNA"]
    assert rows[0].source == "exchange_listings"


def test_cli_batches_selected_tickers_with_full_universe_rows(
    tmp_path,
    monkeypatch,
    capsys,
):
    from src.data_ingestion.download_executor import DownloadSummary
    from scripts import ingest_universe_company_data as cli

    _write_snapshot(tmp_path)
    captured_requests = []

    def fake_run_download(request, *, universe_rows):
        captured_requests.append((request, list(universe_rows)))
        return DownloadSummary(
            data_snapshot_id="snap_20260513_tiingo",
            run_id=f"run_{len(captured_requests)}",
            dry_run=request.dry_run,
            providers=request.providers,
            universe_member_count=2,
            planned_units=len(request.include_tickers or ()),
            completed_units=0,
            skipped_units=0,
            failed_units=0,
            rate_limited_units=0,
            manifest_path=None,
        )

    monkeypatch.setattr(cli, "run_download", fake_run_download)
    args = [
        "prog",
        "--snapshot-date",
        "2026-05-13",
        "--start-date",
        "2026-05-01",
        "--end-date",
        "2026-05-13",
        "--providers",
        "tiingo,sec",
        "--batch-size",
        "1",
        "--include-tickers",
        "MRNA,ABBA",
        "--dry-run",
        "--research-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(cli.sys, "argv", args)

    exit_code = cli.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["selected_tickers"] == ["ABBA", "MRNA"]
    assert [request.include_tickers for request, _ in captured_requests] == [
        ("ABBA",),
        ("MRNA",),
    ]
    assert all(len(universe_rows) == 3 for _, universe_rows in captured_requests)
    assert all(request.resume is True for request, _ in captured_requests)
    assert output["alignment"] == {"status": "not_requested"}


def test_cli_resume_defaults_to_on_and_can_be_disabled():
    from scripts import ingest_universe_company_data as cli

    common_args = [
        "--snapshot-date",
        "2026-05-13",
        "--start-date",
        "2026-05-01",
        "--end-date",
        "2026-05-13",
    ]
    parser = cli.build_arg_parser()

    assert parser.parse_args(common_args).resume is True
    assert parser.parse_args([*common_args, "--no-resume"]).resume is False


def test_alignment_skips_existing_partition_without_replace(tmp_path):
    from scripts.ingest_universe_company_data import align_trusted_events_for_snapshot

    existing = (
        tmp_path
        / "event_price_links"
        / "data_snapshot_id=snap_20260513_tiingo"
        / "event_price_links.parquet"
    )
    existing.parent.mkdir(parents=True)
    existing.write_text("existing", encoding="utf-8")

    summary = align_trusted_events_for_snapshot(
        tickers=["MRNA"],
        data_snapshot_id="snap_20260513_tiingo",
        start_date="2026-05-01",
        end_date="2026-05-13",
        research_dir=tmp_path,
        events_db=tmp_path / "events.db",
        output_root=tmp_path / "event_price_links",
        replace=False,
    )

    assert summary == {
        "status": "skipped",
        "reason": "event_links_exist",
        "path": str(existing),
    }


def test_alignment_writes_combined_links_with_replace(tmp_path, monkeypatch):
    from scripts import ingest_universe_company_data as cli

    def fake_events(ticker, *, start_date, end_date, events_db):
        return pd.DataFrame(
            [{"id": f"evt-{ticker}", "date": "2026-05-04", "ticker_scope": ticker}]
        )

    def fake_prices(ticker, *, data_snapshot_id, output_root, source):
        return pd.DataFrame([{"date": "2026-05-05"}])

    monkeypatch.setattr(cli, "_trusted_events_frame", fake_events)
    monkeypatch.setattr(cli, "load_prices_daily_ohlc", fake_prices)

    summary = cli.align_trusted_events_for_snapshot(
        tickers=["ABBA", "MRNA"],
        data_snapshot_id="snap_20260513_tiingo",
        start_date="2026-05-01",
        end_date="2026-05-13",
        research_dir=tmp_path,
        events_db=tmp_path / "events.db",
        output_root=tmp_path / "event_price_links",
        replace=True,
    )

    assert summary["status"] == "written"
    assert summary["rows"] == 2
    assert Path(summary["path"]).exists()
