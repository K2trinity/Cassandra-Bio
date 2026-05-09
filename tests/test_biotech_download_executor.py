from __future__ import annotations

import json
import pytest

from src.backtest.universe_builder import UniverseSourceRow
from src.data_ingestion.provider_result import ProviderResult


class FakeTiingoClient:
    def __init__(self, result: ProviderResult | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self.result = result

    def fetch_daily_prices(self, *, ticker: str, start_date: str, end_date: str):
        self.calls.append(
            {"ticker": ticker, "start_date": start_date, "end_date": end_date}
        )
        if self.result is not None:
            return self.result
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


class FakeSecClient:
    def __init__(
        self,
        *,
        submissions: ProviderResult | None = None,
        companyfacts: ProviderResult | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.submissions = submissions or ProviderResult(
            status="success",
            request_hash="req_sec_submissions",
            payload={"cik": "0000001", "entityType": "operating"},
        )
        self.companyfacts = companyfacts or ProviderResult(
            status="success",
            request_hash="req_sec_companyfacts",
            payload={
                "facts": {
                    "us-gaap": {
                        "ResearchAndDevelopmentExpense": {
                            "units": {
                                "USD": [
                                    {
                                        "fy": "2025",
                                        "fp": "FY",
                                        "form": "10-K",
                                        "filed": "2026-02-20",
                                        "end": "2025-12-31",
                                        "val": "42.5",
                                    }
                                ]
                            }
                        }
                    }
                }
            },
        )

    def fetch_submissions(self, cik: str):
        self.calls.append(("submissions", str(cik)))
        return self.submissions

    def fetch_companyfacts(self, cik: str):
        self.calls.append(("companyfacts", str(cik)))
        return self.companyfacts


class FakeFmpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch_profile(self, ticker: str):
        self.calls.append(("profile", ticker))
        return ProviderResult(
            status="success",
            request_hash="req_fmp_profile",
            payload=[{"symbol": ticker, "companyName": "ABBA Therapeutics"}],
        )

    def fetch_income_statement(self, ticker: str, period: str = "quarter"):
        self.calls.append(("income", ticker))
        return ProviderResult(
            status="success",
            request_hash="req_fmp_income",
            payload=[
                {
                    "calendarYear": "2025",
                    "period": "FY",
                    "date": "2025-12-31",
                    "fillingDate": "2026-02-20",
                    "reportedCurrency": "USD",
                    "researchAndDevelopmentExpenses": "14.0",
                    "sellingGeneralAndAdministrativeExpenses": "5.0",
                    "revenue": "1.0",
                    "netIncome": "-20.0",
                }
            ],
        )

    def fetch_balance_sheet(self, ticker: str, period: str = "quarter"):
        self.calls.append(("balance", ticker))
        return ProviderResult(
            status="success",
            request_hash="req_fmp_balance",
            payload=[
                {
                    "calendarYear": "2025",
                    "period": "FY",
                    "date": "2025-12-31",
                    "cashAndCashEquivalents": "30.0",
                    "shortTermInvestments": "10.0",
                    "totalDebt": "2.0",
                }
            ],
        )

    def fetch_cash_flow(self, ticker: str, period: str = "quarter"):
        self.calls.append(("cash_flow", ticker))
        return ProviderResult(
            status="success",
            request_hash="req_fmp_cash_flow",
            payload=[
                {
                    "calendarYear": "2025",
                    "period": "FY",
                    "date": "2025-12-31",
                    "operatingCashFlow": "-8.0",
                }
            ],
        )


class FakeFmpProfileOnlyClient(FakeFmpClient):
    def fetch_income_statement(self, ticker: str, period: str = "quarter"):
        self.calls.append(("income", ticker))
        return ProviderResult(
            status="fatal_error",
            request_hash="req_fmp_income_entitlement",
            message="HTTP 402",
        )

    def fetch_balance_sheet(self, ticker: str, period: str = "quarter"):
        self.calls.append(("balance", ticker))
        raise AssertionError("balance sheet should not be fetched after entitlement failure")

    def fetch_cash_flow(self, ticker: str, period: str = "quarter"):
        self.calls.append(("cash_flow", ticker))
        raise AssertionError("cash flow should not be fetched after entitlement failure")


class FakeLimiter:
    def __init__(self, allowed_requests: int | None = None) -> None:
        self.allowed_requests = allowed_requests
        self.calls: list[str] = []

    def allow(self, provider: str):
        from src.data_ingestion.rate_limit import RateLimitDecision

        self.calls.append(provider)
        if self.allowed_requests is None:
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
        if len(self.calls) <= self.allowed_requests:
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
        return RateLimitDecision(allowed=False, retry_after_seconds=86400.0)


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


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)


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
    assert not (tmp_path / "prices_daily").exists()

    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        assert conn.execute("SELECT count(*) FROM provider_fetch_log").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM data_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM universe_snapshots").fetchone()[0] == 0
    finally:
        conn.close()


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
    assert summary.run_id != summary.data_snapshot_id
    assert is_completed(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.run_id,
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
            run_id=dry_summary.run_id,
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
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)
    assert manifest["skipped"][0]["reason"] == "already_completed"


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
    assert manifest["metadata"]["run_id"] == summary.run_id
    assert manifest["survivorship_bias_warning"] is True
    assert manifest["universe_bias_status"] == "current_constituents_only"


def test_different_execution_plans_can_share_data_snapshot_id(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    base = dict(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo",),
        dry_run=False,
        research_dir=tmp_path,
    )

    first = run_download(
        DownloadRequest(**base, limit_tickers=1),
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(),
    )
    second = run_download(
        DownloadRequest(**base, limit_tickers=2),
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(),
    )

    assert first.data_snapshot_id == second.data_snapshot_id
    assert first.run_id != second.run_id
    assert first.manifest_path != second.manifest_path


def test_tiingo_success_with_no_rows_is_skipped_without_success_checkpoint(tmp_path):
    from src.data_ingestion.checkpoints import get_checkpoint
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    client = FakeTiingoClient(
        ProviderResult(status="success", request_hash="req_empty", rows=[])
    )

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo",),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        tiingo_client=client,
    )

    assert summary.completed_units == 0
    assert summary.skipped_units == 1
    assert not list((tmp_path / "prices_daily").rglob("*.parquet"))
    checkpoint = get_checkpoint(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.run_id,
        provider="tiingo",
        phase="prices",
        ticker="ABBA",
        endpoint="/tiingo/daily/ABBA/prices",
        period_start="2026-05-01",
        period_end="2026-05-08",
    )
    assert checkpoint is not None
    assert checkpoint.status == "skipped"
    assert checkpoint.last_error == "no_rows"
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)
    assert manifest["skipped"][0]["reason"] == "no_rows"


def test_tiingo_success_with_no_valid_rows_is_skipped(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    client = FakeTiingoClient(
        ProviderResult(
            status="success",
            request_hash="req_invalid",
            rows=[
                {
                    "date": "not-a-date",
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
    )

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo",),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        tiingo_client=client,
    )

    assert summary.skipped_units == 1
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)
    assert manifest["skipped"][0]["reason"] == "no_valid_rows"


def test_stubbed_providers_fail_without_executable_provider(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("sec", "fmp"),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
            fmp_client=object(),
        )

    message = str(exc_info.value)
    assert "no executable provider" in message.lower()
    assert "SEC_USER_AGENT" not in message
    assert "FMP_API_KEY" not in message


def test_no_executable_provider_fails_default_mixed_request(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("nasdaq", "sec", "tiingo", "fmp"),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
        )

    message = str(exc_info.value)
    assert "no executable provider" in message.lower()
    assert "credential" in message.lower()
    assert "TIINGO_API_KEY" not in message
    assert "SEC_USER_AGENT" not in message
    assert "FMP_API_KEY" not in message


def test_executable_tiingo_allows_mixed_stubbed_provider_skips(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo", "sec"),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(),
    )

    assert summary.completed_units == 1
    assert summary.skipped_units == 1
    assert summary.failed_units == 0
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)
    reasons = {item["provider"]: item["reason"] for item in manifest["skipped"]}
    assert reasons == {"sec": "missing_client"}


def test_missing_tiingo_key_fails_when_tiingo_is_only_requested(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("tiingo",),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
        )

    message = str(exc_info.value)
    assert "tiingo" in message.lower()
    assert "credential" in message.lower()
    assert "TIINGO_API_KEY" not in message


def test_missing_sec_user_agent_fails_when_only_stubbed_provider_can_run(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("sec", "fmp"),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
            fmp_client=object(),
        )

    message = str(exc_info.value)
    assert "no executable provider" in message.lower()
    assert "SEC_USER_AGENT" not in message


def test_missing_sec_user_agent_fails_when_sec_is_only_requested(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("sec",),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
        )

    message = str(exc_info.value)
    assert "sec" in message.lower()
    assert "credential" in message.lower()
    assert "SEC_USER_AGENT" not in message


def test_missing_fmp_key_skips_fmp_when_sec_can_run(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("SEC_USER_AGENT", "CassandraBio user@example.com")

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("sec", "fmp"),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        sec_client=FakeSecClient(),
        rate_limiters={"sec": FakeLimiter()},
    )

    assert summary.completed_units == 1
    assert summary.skipped_units == 1
    with open(summary.manifest_path, encoding="utf-8") as file:
        manifest = json.load(file)
    reasons = {item["provider"]: item["reason"] for item in manifest["skipped"]}
    assert reasons == {"fmp": "missing_client"}


def test_missing_fmp_key_fails_when_fmp_is_only_requested(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    with pytest.raises(RuntimeError) as exc_info:
        run_download(
            DownloadRequest(
                snapshot_date="2026-05-08",
                start_date="2026-05-01",
                end_date="2026-05-08",
                providers=("fmp",),
                dry_run=False,
                limit_tickers=1,
                research_dir=tmp_path,
            ),
            universe_rows=_universe_rows(),
        )

    message = str(exc_info.value)
    assert "fmp" in message.lower()
    assert "credential" in message.lower()
    assert "FMP_API_KEY" not in message


def test_injected_provider_clients_do_not_require_credentials(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo", "sec", "fmp"),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(),
        sec_client=FakeSecClient(),
        fmp_client=FakeFmpClient(),
        rate_limiters={
            "tiingo": FakeLimiter(),
            "sec": FakeLimiter(),
            "fmp": FakeLimiter(),
        },
    )

    assert summary.completed_units == 3
    assert summary.skipped_units == 0


def test_executor_downloads_sec_submissions_and_companyfacts_then_writes_logs(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.checkpoints import get_checkpoint
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    sec_client = FakeSecClient()
    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("sec",),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        sec_client=sec_client,
        rate_limiters={"sec": FakeLimiter()},
    )

    assert summary.completed_units == 1
    assert summary.failed_units == 0
    assert sec_client.calls == [("submissions", "0000001"), ("companyfacts", "0000001")]

    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        logs = conn.execute(
            """
            SELECT endpoint, request_hash, status
            FROM provider_fetch_log
            WHERE provider = 'sec'
            ORDER BY endpoint
            """
        ).fetchall()
        facts = conn.execute(
            """
            SELECT ticker, cik, concept, fiscal_year, fiscal_period, value, source
            FROM sec_companyfacts_normalized
            """
        ).fetchall()
    finally:
        conn.close()

    assert logs == [
        ("/sec/companyfacts/0000001", "req_sec_companyfacts", "success"),
        ("/sec/submissions/0000001", "req_sec_submissions", "success"),
    ]
    assert facts == [
        (
            "ABBA",
            "0000000001",
            "ResearchAndDevelopmentExpense",
            2025,
            "FY",
            42.5,
            "sec_companyfacts",
        )
    ]
    checkpoint = get_checkpoint(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.run_id,
        provider="sec",
        phase="companyfacts",
        ticker="ABBA",
        endpoint="/sec/companyfacts/0000001",
    )
    assert checkpoint is not None
    assert checkpoint.status == "success"


def test_executor_downloads_fmp_profile_and_statements_then_writes_logs(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.download_executor import DownloadRequest, run_download

    fmp_client = FakeFmpClient()
    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("fmp",),
            dry_run=False,
            limit_tickers=1,
            daily_fmp_budget=10,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        fmp_client=fmp_client,
        rate_limiters={"fmp": FakeLimiter()},
    )

    assert summary.completed_units == 1
    assert summary.failed_units == 0
    assert fmp_client.calls == [
        ("profile", "ABBA"),
        ("income", "ABBA"),
        ("balance", "ABBA"),
        ("cash_flow", "ABBA"),
    ]

    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        logs = conn.execute(
            """
            SELECT endpoint, request_hash, status
            FROM provider_fetch_log
            WHERE provider = 'fmp'
            ORDER BY endpoint
            """
        ).fetchall()
        row = conn.execute(
            """
            SELECT ticker, fiscal_period, source, payload_json
            FROM fundamentals_normalized
            WHERE source = 'fmp'
            """
        ).fetchone()
    finally:
        conn.close()

    assert logs == [
        ("/fmp/balance-sheet-statement/ABBA", "req_fmp_balance", "success"),
        ("/fmp/cash-flow-statement/ABBA", "req_fmp_cash_flow", "success"),
        ("/fmp/income-statement/ABBA", "req_fmp_income", "success"),
        ("/fmp/profile/ABBA", "req_fmp_profile", "success"),
    ]
    assert row[:3] == ("ABBA", "2025-FY", "fmp")
    payload = json.loads(row[3])
    assert payload["cash_and_short_term_investments"] == 40.0
    assert payload["operating_cash_flow"] == -8.0
    assert payload["cash_runway_quarters"] == 5.0


def test_executor_treats_fmp_statement_entitlement_as_profile_only_success(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.checkpoints import get_checkpoint
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    fmp_client = FakeFmpProfileOnlyClient()
    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("fmp",),
            dry_run=False,
            limit_tickers=1,
            daily_fmp_budget=10,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        fmp_client=fmp_client,
        rate_limiters={"fmp": FakeLimiter()},
    )

    assert summary.completed_units == 1
    assert summary.failed_units == 0
    assert fmp_client.calls == [
        ("profile", "ABBA"),
        ("income", "ABBA"),
    ]

    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        logs = conn.execute(
            """
            SELECT endpoint, request_hash, status, message
            FROM provider_fetch_log
            WHERE provider = 'fmp'
            ORDER BY endpoint
            """
        ).fetchall()
        fundamentals_count = conn.execute(
            """
            SELECT count(*)
            FROM fundamentals_normalized
            WHERE source = 'fmp'
            """
        ).fetchone()[0]
    finally:
        conn.close()

    checkpoint = get_checkpoint(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.run_id,
        provider="fmp",
        phase="profile",
        ticker="ABBA",
        endpoint="/fmp/profile/ABBA",
        period_start="2026-05-01",
        period_end="2026-05-08",
    )
    assert checkpoint is not None
    assert checkpoint.status == "success"
    assert checkpoint.last_error == "optional_statements_unavailable: HTTP 402"
    assert logs == [
        (
            "/fmp/income-statement/ABBA",
            "req_fmp_income_entitlement",
            "fatal_error",
            "HTTP 402",
        ),
        ("/fmp/profile/ABBA", "req_fmp_profile", "success", None),
    ]
    assert fundamentals_count == 0


def test_executor_marks_provider_runtime_budget_exhaustion_rate_limited(
    tmp_path,
    monkeypatch,
):
    _clear_provider_env(monkeypatch)

    from src.data_ingestion.checkpoints import get_checkpoint
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    fmp_client = FakeFmpClient()
    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("fmp",),
            dry_run=False,
            limit_tickers=1,
            daily_fmp_budget=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        fmp_client=fmp_client,
        rate_limiters={"fmp": FakeLimiter(allowed_requests=0)},
    )

    assert summary.completed_units == 0
    assert summary.rate_limited_units == 1
    assert fmp_client.calls == []

    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        logs = conn.execute(
            """
            SELECT endpoint, status, message
            FROM provider_fetch_log
            WHERE provider = 'fmp'
            """
        ).fetchall()
    finally:
        conn.close()

    assert logs == [
        ("/fmp/profile/ABBA", "rate_limited", "runtime rate limit exhausted")
    ]
    checkpoint = get_checkpoint(
        db_path=tmp_path / "cassandra_research.duckdb",
        run_id=summary.run_id,
        provider="fmp",
        phase="profile",
        ticker="ABBA",
        endpoint="/fmp/profile/ABBA",
        period_start="2026-05-01",
        period_end="2026-05-08",
    )
    assert checkpoint is not None
    assert checkpoint.status == "rate_limited"


def test_tiingo_rate_limited_and_failed_statuses_update_counts(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo",),
        dry_run=False,
        limit_tickers=1,
        research_dir=tmp_path / "rate",
    )

    rate_limited = run_download(
        request,
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(
            ProviderResult(
                status="rate_limited",
                request_hash="req_rate",
                message="slow down",
                retry_after_seconds=60,
            )
        ),
    )
    assert rate_limited.rate_limited_units == 1
    assert rate_limited.failed_units == 0

    failed = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo",),
            dry_run=False,
            limit_tickers=1,
            research_dir=tmp_path / "failed",
        ),
        universe_rows=_universe_rows(),
        tiingo_client=FakeTiingoClient(
            ProviderResult(status="failed", request_hash="req_fail", message="fatal")
        ),
    )
    assert failed.failed_units == 1
    assert failed.rate_limited_units == 0


def test_normalization_failure_does_not_write_synthetic_provider_fetch(tmp_path):
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    client = FakeTiingoClient(
        ProviderResult(
            status="success",
            request_hash="req_bad",
            rows=[{"date": "2026-05-01T00:00:00.000Z"}],
        )
    )

    summary = run_download(
        DownloadRequest(
            snapshot_date="2026-05-08",
            start_date="2026-05-01",
            end_date="2026-05-08",
            providers=("tiingo",),
            dry_run=False,
            resume=False,
            limit_tickers=1,
            research_dir=tmp_path,
        ),
        universe_rows=_universe_rows(),
        tiingo_client=client,
    )

    assert summary.failed_units == 1
    import duckdb

    conn = duckdb.connect(str(tmp_path / "cassandra_research.duckdb"))
    try:
        rows = conn.execute(
            "SELECT request_hash, status FROM provider_fetch_log"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("req_bad", "success")]
