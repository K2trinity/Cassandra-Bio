from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def _base_command(tmp_path: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/download_biotech_data.py",
        "--snapshot-date",
        "2026-05-08",
        "--start-date",
        "2026-05-01",
        "--end-date",
        "2026-05-08",
        "--research-dir",
        str(tmp_path / "research"),
    ]


def _clean_provider_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"TIINGO_API_KEY", "SEC_USER_AGENT", "FMP_API_KEY"}
    }


def test_download_biotech_data_help_does_not_require_credentials():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/download_biotech_data.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--snapshot-date" in result.stdout
    assert "--providers" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--limit-tickers" in result.stdout


def test_download_biotech_data_loads_nasdaq_trader_when_fixture_missing():
    from scripts.download_biotech_data import _load_universe_rows
    from src.data_ingestion.nasdaq_trader import NasdaqTraderDirectoryResult

    def fake_fetch():
        return (
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="nasdaqlisted",
                request_hash="req_nasdaq",
                status="success",
                payload="\n".join(
                    [
                        "Symbol|Security Name|Market Category|Test Issue|"
                        "Financial Status|Round Lot Size|ETF|NextShares",
                        "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
                    ]
                ),
            ),
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="otherlisted",
                request_hash="req_other",
                status="success",
                payload="\n".join(
                    [
                        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|"
                        "Round Lot Size|Test Issue|NASDAQ Symbol",
                        "DNA|Ginkgo Bioworks Holdings Inc Class A Common Stock|"
                        "N|DNA|N|100|N|DNA",
                    ]
                ),
            ),
        )

    rows = _load_universe_rows(None, nasdaq_fetcher=fake_fetch)

    assert [row.ticker for row in rows] == ["MRNA", "DNA"]


def test_download_biotech_data_logs_nasdaq_trader_fetch_results(tmp_path):
    from scripts.download_biotech_data import _load_universe_rows
    from src.data_ingestion.nasdaq_trader import NasdaqTraderDirectoryResult

    def fake_fetch():
        return (
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="nasdaqlisted",
                request_hash="req_nasdaq",
                status="success",
                payload="\n".join(
                    [
                        "Symbol|Security Name|Market Category|Test Issue|"
                        "Financial Status|Round Lot Size|ETF|NextShares",
                        "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
                    ]
                ),
            ),
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="otherlisted",
                request_hash="req_other",
                status="success",
                payload="\n".join(
                    [
                        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|"
                        "Round Lot Size|Test Issue|NASDAQ Symbol",
                        "DNA|Ginkgo Bioworks Holdings Inc Class A Common Stock|"
                        "N|DNA|N|100|N|DNA",
                    ]
                ),
            ),
        )

    _load_universe_rows(
        None,
        db_path=tmp_path / "research.duckdb",
        nasdaq_fetcher=fake_fetch,
    )

    import duckdb

    conn = duckdb.connect(str(tmp_path / "research.duckdb"))
    try:
        logs = conn.execute(
            """
            SELECT provider, endpoint, request_hash, status
            FROM provider_fetch_log
            ORDER BY endpoint
            """
        ).fetchall()
    finally:
        conn.close()

    assert logs == [
        ("nasdaq_trader", "nasdaqlisted", "req_nasdaq", "success"),
        ("nasdaq_trader", "otherlisted", "req_other", "success"),
    ]


def test_download_biotech_data_rejects_incomplete_nasdaq_trader_fetch():
    from scripts.download_biotech_data import _load_universe_rows
    from src.data_ingestion.nasdaq_trader import NasdaqTraderDirectoryResult

    def fake_fetch():
        return (
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="nasdaqlisted",
                request_hash="req_nasdaq",
                status="rate_limited",
                message="HTTP 429",
                retry_after_seconds=60,
            ),
            NasdaqTraderDirectoryResult(
                provider="nasdaq_trader",
                endpoint="otherlisted",
                request_hash="req_other",
                status="success",
                payload="ACT Symbol|Security Name|Exchange|ETF|Test Issue",
            ),
        )

    with pytest.raises(RuntimeError, match="Nasdaq Trader universe fetch incomplete"):
        _load_universe_rows(None, nasdaq_fetcher=fake_fetch)


def test_download_biotech_data_dry_run_uses_fixture_universe(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/download_biotech_data.py",
            "--snapshot-date",
            "2026-05-08",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-08",
            "--providers",
            "tiingo,sec",
            "--dry-run",
            "--limit-tickers",
            "1",
            "--exchange-listings-csv",
            str(fixture),
            "--research-dir",
            str(tmp_path / "research"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["dry_run"] is True
    assert summary["universe_member_count"] == 1
    assert summary["planned_units"] == 2
    combined_output = result.stdout + result.stderr
    assert "TIINGO_API_KEY" not in combined_output
    assert "FMP_API_KEY" not in combined_output
    assert "SEC_USER_AGENT" not in combined_output


def test_download_biotech_data_default_non_dry_run_requires_executable_provider(
    tmp_path,
):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            *_base_command(tmp_path),
            "--limit-tickers",
            "1",
            "--exchange-listings-csv",
            str(fixture),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "no executable provider" in result.stderr.lower()
    assert "credential" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert "TIINGO_API_KEY" not in result.stderr
    assert "SEC_USER_AGENT" not in result.stderr
    assert "FMP_API_KEY" not in result.stderr
    assert result.stdout == ""


def test_download_biotech_data_rejects_fixture_with_missing_header(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange\n"
        "MRNA,Moderna Inc,NASDAQ\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            *_base_command(tmp_path),
            "--dry-run",
            "--exchange-listings-csv",
            str(fixture),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "missing required columns" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_download_biotech_data_rejects_fixture_with_blank_required_field(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            *_base_command(tmp_path),
            "--dry-run",
            "--exchange-listings-csv",
            str(fixture),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "row 2" in result.stderr.lower()
    assert "company_name" in result.stderr
    assert "Traceback" not in result.stderr


def test_download_biotech_data_rejects_unknown_provider_before_run(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            *_base_command(tmp_path),
            "--dry-run",
            "--providers",
            "tiingo,unknown",
            "--exchange-listings-csv",
            str(fixture),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "unsupported provider" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_download_biotech_data_fmp_only_missing_credentials_fails_without_traceback(
    tmp_path,
):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            *_base_command(tmp_path),
            "--providers",
            "fmp",
            "--exchange-listings-csv",
            str(fixture),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "fmp" in result.stderr.lower()
    assert "credential" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert "FMP_API_KEY" not in result.stderr
