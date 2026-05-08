from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys


def test_build_biotech_universe_snapshot_script_help_runs_from_repo_root():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/build_biotech_universe_snapshot.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--xbi-holdings" in result.stdout
    assert "--ibb-holdings" in result.stdout
    assert "--exchange-listings" in result.stdout


def test_build_snapshot_from_csvs_writes_universe_catalog_tables(tmp_path):
    import duckdb

    from scripts.build_biotech_universe_snapshot import build_snapshot_from_csvs

    xbi_path = tmp_path / "xbi.csv"
    ibb_path = tmp_path / "ibb.csv"
    listings_path = tmp_path / "exchange_listings.csv"
    db_path = tmp_path / "research.duckdb"
    _write_csv(
        xbi_path,
        [
            {
                "ticker": "MRNA",
                "company_name": "Moderna, Inc.",
                "exchange": "NASDAQ",
                "asset_type": "common_stock",
                "source_weight": "0.012",
                "industry": "Biotechnology",
                "cik": "1682852",
                "cusip": "60770K107",
                "isin": "US60770K1079",
            }
        ],
    )
    _write_csv(
        ibb_path,
        [
            {
                "ticker": "JNJ",
                "company_name": "Johnson & Johnson",
                "exchange": "NYSE",
                "asset_type": "common_stock",
                "source_weight": "0.018",
            }
        ],
    )
    _write_csv(
        listings_path,
        [
            {
                "ticker": "XBI",
                "company_name": "SPDR S&P Biotech ETF",
                "exchange": "NYSEARCA",
                "asset_type": "ETF",
            }
        ],
    )

    summary = build_snapshot_from_csvs(
        xbi_holdings=xbi_path,
        ibb_holdings=ibb_path,
        exchange_listings=listings_path,
        db_path=db_path,
        as_of_date="2026-05-08",
    )

    assert summary == {
        "universe_id": "biotech_us_v1",
        "member_count": 2,
        "benchmark_tickers": ["XBI"],
        "bias_status": "current_constituents_only",
        "survivorship_bias_warning": True,
    }

    conn = duckdb.connect(str(db_path))
    try:
        snapshot_row = conn.execute(
            """
            SELECT
                universe_id,
                CAST(as_of_date AS VARCHAR),
                bias_status,
                survivorship_bias_warning,
                member_count,
                benchmark_tickers_json
            FROM universe_snapshots
            """
        ).fetchone()
        membership_rows = conn.execute(
            """
            SELECT
                universe_id,
                security_id,
                ticker,
                CAST(member_from AS VARCHAR),
                member_to,
                weight,
                membership_source,
                CAST(as_of_date AS VARCHAR)
            FROM universe_membership
            ORDER BY ticker
            """
        ).fetchall()
    finally:
        conn.close()

    assert snapshot_row[:5] == (
        "biotech_us_v1",
        "2026-05-08",
        "current_constituents_only",
        True,
        2,
    )
    assert json.loads(snapshot_row[5]) == ["XBI"]
    assert membership_rows == [
        (
            "biotech_us_v1",
            "BIO:JNJ",
            "JNJ",
            "2026-05-08",
            None,
            None,
            "ibb",
            "2026-05-08",
        ),
        (
            "biotech_us_v1",
            "BIO:MRNA",
            "MRNA",
            "2026-05-08",
            None,
            None,
            "xbi",
            "2026-05-08",
        ),
    ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "company_name",
        "exchange",
        "asset_type",
        "source_weight",
        "industry",
        "cik",
        "cusip",
        "isin",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
