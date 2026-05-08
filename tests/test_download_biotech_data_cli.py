from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


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


def test_download_biotech_data_dry_run_requires_exchange_listing_fixture(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [*_base_command(tmp_path), "--dry-run"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "exchange-listings-csv" in result.stderr
    assert "required" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_download_biotech_data_non_dry_run_requires_exchange_listing_fixture(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        _base_command(tmp_path),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_provider_env(),
    )

    assert result.returncode != 0
    assert "exchange-listings-csv" in result.stderr
    assert "required" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


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
