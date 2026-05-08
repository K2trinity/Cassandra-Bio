from __future__ import annotations

import json

from src.backtest.universe_builder import UniverseSourceRow
from src.data_ingestion.provider_result import ProviderResult


class FakeTiingoClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def fetch_daily_prices(self, *, ticker: str, start_date: str, end_date: str):
        self.calls.append(
            {"ticker": ticker, "start_date": start_date, "end_date": end_date}
        )
        return ProviderResult(
            status="success",
            request_hash=f"req_{ticker}",
            rows=[
                {
                    "date": "2026-05-01T00:00:00.000Z",
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 103.0,
                    "volume": 12345,
                    "adjOpen": 50.0,
                    "adjHigh": 52.5,
                    "adjLow": 49.5,
                    "adjClose": 51.5,
                    "adjVolume": 24690,
                    "divCash": 0.0,
                    "splitFactor": 2.0,
                }
            ],
        )


def _universe_rows() -> list[UniverseSourceRow]:
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
    ]


def test_dry_run_plans_units_without_fetching_and_returns_member_count(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo", "sec"),
        dry_run=True,
        limit_tickers=1,
        research_dir=tmp_path,
    )
    client = FakeTiingoClient()

    summary = run_download(request, universe_rows=_universe_rows(), tiingo_client=client)

    assert summary.dry_run is True
    assert summary.planned_units == 2
    assert summary.completed_units == 0
    assert summary.skipped_units == 0
    assert summary.universe_member_count == 2
    assert client.calls == []


def test_executor_downloads_tiingo_prices_and_checkpoints_success(tmp_path):
    from src.data_ingestion.checkpoints import is_completed
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo",),
        dry_run=False,
        limit_tickers=1,
        research_dir=tmp_path,
    )
    client = FakeTiingoClient()

    summary = run_download(request, universe_rows=_universe_rows(), tiingo_client=client)

    assert summary.completed_units == 1
    assert summary.failed_units == 0
    assert client.calls == [
        {
            "ticker": "ABBA",
            "start_date": "2026-05-01",
            "end_date": "2026-05-08",
        }
    ]
    assert list((tmp_path / "prices_daily").rglob("*.parquet"))
    assert is_completed(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.data_snapshot_id,
        provider="tiingo",
        phase="prices",
        ticker="ABBA",
        endpoint="/tiingo/daily/ABBA/prices",
        period_start="2026-05-01",
        period_end="2026-05-08",
    )


def test_resume_skips_completed_tiingo_checkpoint_without_calling_client(tmp_path):
    from src.data_ingestion.checkpoints import IngestionCheckpoint, record_checkpoint
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo",),
        dry_run=False,
        limit_tickers=1,
        research_dir=tmp_path,
    )
    dry_summary = run_download(
        DownloadRequest(
            snapshot_date=request.snapshot_date,
            start_date=request.start_date,
            end_date=request.end_date,
            providers=request.providers,
            dry_run=True,
            limit_tickers=request.limit_tickers,
            research_dir=request.research_dir,
        ),
        universe_rows=_universe_rows(),
    )
    record_checkpoint(
        IngestionCheckpoint(
            run_id=dry_summary.data_snapshot_id,
            data_snapshot_id=dry_summary.data_snapshot_id,
            provider="tiingo",
            phase="prices",
            ticker="ABBA",
            endpoint="/tiingo/daily/ABBA/prices",
            period_start="2026-05-01",
            period_end="2026-05-08",
            status="success",
            attempt_count=1,
            last_error=None,
        ),
        db_path=tmp_path / "cassandra_research.duckdb",
    )
    client = FakeTiingoClient()

    summary = run_download(request, universe_rows=_universe_rows(), tiingo_client=client)

    assert summary.skipped_units == 1
    assert summary.completed_units == 0
    assert client.calls == []


def test_manifest_exists_and_includes_survivorship_warning(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo", "sec"),
            dry_run=True,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
    )

    assert summary.manifest_path is not None
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)

    assert manifest["data_snapshot_id"] == summary.data_snapshot_id
    assert manifest["survivorship_bias_warning"] is True
    assert manifest["universe_bias_status"] == "current_constituents_only"
