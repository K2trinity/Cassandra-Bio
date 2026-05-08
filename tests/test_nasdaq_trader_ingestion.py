from __future__ import annotations


def test_parse_nasdaq_listed_filters_etfs_test_issues_and_keeps_common_like_rows():
    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
            "XBI|SPDR S&P Biotech ETF|G|N|N|100|Y|N",
            "TEST|Test Company Common Stock|Q|Y|N|100|N|N",
            "File Creation Time: 0508202618:03|||||||",
        ]
    )

    rows = parse_nasdaq_listed(text)

    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "MRNA"
    assert row.exchange == "NASDAQ"
    assert row.asset_type == "common_stock"
    assert row.source == "exchange_listings"


def test_parse_otherlisted_maps_exchange_and_skips_non_common_share_classes():
    from src.data_ingestion.nasdaq_trader import parse_otherlisted

    text = "\n".join(
        [
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
            "DNA|Ginkgo Bioworks Holdings Inc Class A Common Stock|N|DNA|N|100|N|DNA",
            "ABC.W|ABC Corp Warrant|A|ABC.W|N|100|N|ABC.W",
            "File Creation Time: 0508202618:03|||||||",
        ]
    )

    rows = parse_otherlisted(text)

    assert [row.ticker for row in rows] == ["DNA"]
    assert rows[0].exchange == "NYSE"
