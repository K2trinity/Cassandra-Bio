from __future__ import annotations

import json


def test_build_universe_snapshot_filters_benchmarks_and_merges_sources():
    from src.backtest.universe_builder import (
        BIOTECH_US_UNIVERSE_ID,
        UniverseSourceRow,
        build_universe_snapshot,
    )

    assert BIOTECH_US_UNIVERSE_ID == "biotech_us_v1"

    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="xbi",
                company_name="SPDR S&P Biotech ETF",
                exchange="NYSEARCA",
                asset_type="ETF",
                source="XBI",
                source_weight=0.012,
            ),
            UniverseSourceRow(
                ticker="mrna",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="Common Stock",
                source="XBI",
                source_weight=0.008,
                industry="Biotechnology",
                cik="1682852",
                cusip="60770K107",
                isin="US60770K1079",
            ),
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna Inc",
                exchange="Nasdaq",
                asset_type="common_stock",
                source="IBB",
                source_weight=0.021,
            ),
            UniverseSourceRow(
                ticker="ABBA",
                company_name="ABBA Therapeutics",
                exchange="NASDAQ",
                asset_type="Common Stock",
                source="Manual",
            ),
            UniverseSourceRow(
                ticker="ibb",
                company_name="iShares Biotechnology ETF",
                exchange="NASDAQ",
                asset_type="fund",
                source="IBB",
            ),
            UniverseSourceRow(
                ticker="bbh",
                company_name="VanEck Biotech ETF",
                exchange="NASDAQ",
                asset_type="benchmark_etf",
                source="BBH",
            ),
        ],
        as_of_date="2026-05-08",
    )

    assert snapshot.universe_id == BIOTECH_US_UNIVERSE_ID
    assert snapshot.as_of_date == "2026-05-08"
    assert snapshot.bias_status == "current_constituents_only"
    assert snapshot.survivorship_bias_warning is True
    assert snapshot.benchmark_tickers == ("BBH", "IBB", "XBI")

    assert [member.ticker for member in snapshot.members] == ["ABBA", "MRNA"]
    assert [member.security_id for member in snapshot.members] == [
        "BIO:ABBA",
        "BIO:MRNA",
    ]
    mrna = snapshot.members[1]
    assert mrna.security_id == "BIO:MRNA"
    assert mrna.company_name == "Moderna Inc"
    assert mrna.exchange == "NASDAQ"
    assert mrna.asset_type == "common_stock"
    assert mrna.source_memberships == ("ibb", "xbi")
    assert mrna.source_weights == {"ibb": 0.021, "xbi": 0.008}
    assert mrna.industry == "Biotechnology"
    assert mrna.cik == "1682852"
    assert mrna.cusip == "60770K107"
    assert mrna.isin == "US60770K1079"


def test_universe_snapshot_id_is_deterministic_and_content_addressed():
    from src.backtest.universe_builder import (
        UniverseSourceRow,
        build_universe_snapshot,
    )

    first = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="Common Stock",
                source="XBI",
            ),
            UniverseSourceRow(
                ticker="XBI",
                company_name="SPDR S&P Biotech ETF",
                exchange="NYSEARCA",
                asset_type="benchmark_etf",
                source="XBI",
                source_weight=0.012,
            ),
        ],
        as_of_date="2026-05-08",
    )
    reordered = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="xbi",
                company_name="SPDR S&P Biotech ETF",
                exchange="NYSEARCA",
                asset_type="benchmark_etf",
                source="xbi",
                source_weight=0.012,
            ),
            UniverseSourceRow(
                ticker="mrna",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="xbi",
            ),
        ],
        as_of_date="2026-05-08",
    )
    changed = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="Common Stock",
                source="XBI",
            ),
        ],
        as_of_date="2026-05-09",
    )

    assert first.universe_snapshot_id == reordered.universe_snapshot_id
    assert first.universe_snapshot_id.startswith("univ_20260508_")
    assert first.universe_snapshot_id != changed.universe_snapshot_id


def test_duplicate_member_merge_uses_deterministic_source_precedence():
    from src.backtest.universe_builder import (
        UniverseSourceRow,
        build_universe_snapshot,
    )

    xbi_row = UniverseSourceRow(
        ticker="MRNA",
        company_name="Moderna from XBI",
        exchange="NYSE",
        asset_type="common_stock",
        source="xbi",
        source_weight=0.008,
        industry="Pharma",
        cik="xbi-cik",
    )
    ibb_row = UniverseSourceRow(
        ticker="mrna",
        company_name="Moderna from IBB",
        exchange="Nasdaq",
        asset_type="Common Stock",
        source="IBB",
        source_weight=0.021,
        industry="Biotechnology",
        cusip="60770K107",
    )

    first = build_universe_snapshot(
        [xbi_row, ibb_row],
        as_of_date="2026-05-08",
    )
    reversed_order = build_universe_snapshot(
        [ibb_row, xbi_row],
        as_of_date="2026-05-08",
    )

    assert first.universe_snapshot_id == reversed_order.universe_snapshot_id
    assert first.members == reversed_order.members
    member = first.members[0]
    assert member.company_name == "Moderna from IBB"
    assert member.exchange == "NASDAQ"
    assert member.industry == "Biotechnology"
    assert member.cusip == "60770K107"
    assert member.cik == "xbi-cik"
    assert member.source_memberships == ("ibb", "xbi")


def test_source_payload_order_is_total_for_tied_sort_fields():
    from src.backtest.universe_builder import (
        UniverseSourceRow,
        build_universe_snapshot,
    )

    first_xbi_row = UniverseSourceRow(
        ticker="MRNA",
        company_name="Moderna, Inc.",
        exchange="NASDAQ",
        asset_type="common_stock",
        source="xbi",
        source_weight=0.008,
        cik="1682852",
        cusip="60770K107",
    )
    second_xbi_row = UniverseSourceRow(
        ticker="mrna",
        company_name="Moderna, Inc.",
        exchange="NYSE",
        asset_type="Common Stock",
        source="XBI",
        source_weight=0.012,
        cik="alternate-cik",
        isin="US60770K1079",
    )

    first = build_universe_snapshot(
        [first_xbi_row, second_xbi_row],
        as_of_date="2026-05-08",
    )
    reversed_order = build_universe_snapshot(
        [second_xbi_row, first_xbi_row],
        as_of_date="2026-05-08",
    )

    assert first.universe_snapshot_id == reversed_order.universe_snapshot_id
    assert first.to_catalog_payload()["source_payload_json"] == (
        reversed_order.to_catalog_payload()["source_payload_json"]
    )


def test_universe_snapshot_catalog_payload_uses_json_strings():
    from src.backtest.universe_builder import (
        BIOTECH_US_UNIVERSE_ID,
        UniverseSourceRow,
        build_universe_snapshot,
    )

    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="Common Stock",
                source="XBI",
            ),
            UniverseSourceRow(
                ticker="XBI",
                company_name="SPDR S&P Biotech ETF",
                exchange="NYSEARCA",
                asset_type="benchmark_etf",
                source="XBI",
                source_weight=0.012,
            ),
        ],
        as_of_date="2026-05-08",
    )

    payload = snapshot.to_catalog_payload()

    assert payload["universe_snapshot_id"] == snapshot.universe_snapshot_id
    assert payload["universe_id"] == BIOTECH_US_UNIVERSE_ID
    assert payload["as_of_date"] == "2026-05-08"
    assert payload["bias_status"] == "current_constituents_only"
    assert payload["survivorship_bias_warning"] is True
    assert payload["member_count"] == 1
    assert json.loads(payload["benchmark_tickers_json"]) == ["XBI"]
    assert json.loads(payload["source_payload_json"]) == [
        {
            "asset_type": "common stock",
            "cik": None,
            "company_name": "Moderna, Inc.",
            "cusip": None,
            "exchange": "NASDAQ",
            "industry": None,
            "isin": None,
            "source": "xbi",
            "source_weight": None,
            "ticker": "MRNA",
        },
        {
            "asset_type": "benchmark_etf",
            "cik": None,
            "company_name": "SPDR S&P Biotech ETF",
            "cusip": None,
            "exchange": "NYSEARCA",
            "industry": None,
            "isin": None,
            "source": "xbi",
            "source_weight": 0.012,
            "ticker": "XBI",
        },
    ]
    assert json.loads(payload["coverage_json"]) == {
        "benchmark_tickers": ["XBI"],
        "member_count": 1,
        "sources": ["xbi"],
    }


def test_research_database_creates_universe_snapshots_catalog_table(tmp_path):
    from src.backtest.research_db import initialize_research_database

    db_path = tmp_path / "research.duckdb"

    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info('universe_snapshots')").fetchall()
        }
    finally:
        conn.close()

    assert "universe_snapshots" in tables
    assert {
        "universe_snapshot_id",
        "universe_id",
        "as_of_date",
        "bias_status",
        "survivorship_bias_warning",
        "member_count",
        "benchmark_tickers_json",
        "source_payload_json",
        "coverage_json",
        "created_at",
    }.issubset(columns)
    assert "benchmark_json" not in columns
    assert "source_json" not in columns
