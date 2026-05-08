from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


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
