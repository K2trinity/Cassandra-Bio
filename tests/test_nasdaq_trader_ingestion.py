from __future__ import annotations


def test_parse_nasdaq_listed_filters_etfs_test_issues_and_keeps_common_like_rows():
    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
            "XBI|SPDR S&P Biotech ETF|G|N|N|100|Y|N",
            "TEST|Test Company Common Stock|Q|Y|N|100|N|N",
            "   File Creation Time: 0508202618:03|||||||",
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
            "ABC.U|ABC Corp Unit|A|ABC.U|N|100|N|ABC.U",
            "ABC.R|ABC Corp Rights|A|ABC.R|N|100|N|ABC.R",
            "File Creation Time: 0508202618:03|||||||",
        ]
    )

    rows = parse_otherlisted(text)

    assert [row.ticker for row in rows] == ["DNA"]
    assert rows[0].exchange == "NYSE"


def test_parse_nasdaq_listed_rejects_missing_required_columns():
    import pytest

    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Test Issue",
            "MRNA|Moderna, Inc. Common Stock|N",
        ]
    )

    with pytest.raises(ValueError, match="Missing required Nasdaq listed columns: ETF"):
        parse_nasdaq_listed(text)


def test_parse_otherlisted_rejects_missing_required_columns():
    import pytest

    from src.data_ingestion.nasdaq_trader import parse_otherlisted

    text = "\n".join(
        [
            "ACT Symbol|Security Name|ETF|Test Issue",
            "DNA|Ginkgo Bioworks Holdings Inc Class A Common Stock|N|N",
        ]
    )

    with pytest.raises(ValueError, match="Missing required other listed columns: Exchange"):
        parse_otherlisted(text)


def test_parse_symbol_directories_combines_sources_and_keeps_common_class_tickers():
    from src.data_ingestion.nasdaq_trader import parse_symbol_directories

    nasdaq_text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
            "CDZIP|Cadiz Inc Preferred Depositary Shares|Q|N|N|100|N|N",
        ]
    )
    other_text = "\n".join(
        [
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
            "AKO.A|Embotelladora Andina S.A. Series A Shares|N|AKO.A|N|100|N|AKO.A",
            "BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|100|N|BRK.B",
        ]
    )

    rows = parse_symbol_directories(
        nasdaqlisted_text=nasdaq_text,
        otherlisted_text=other_text,
    )

    assert [row.ticker for row in rows] == ["MRNA", "AKO.A", "BRK.B"]


def test_parse_nasdaq_listed_keeps_common_equivalent_ads_rows():
    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "ARGX|argenx SE - American Depositary Shares|Q|N|N|100|N|N",
            "BNTX|BioNTech SE - American Depositary Shares|Q|N|N|100|N|N",
            "GMAB|Genmab A/S - American Depositary Shares|Q|N|N|100|N|N",
            "LEGN|Legend Biotech Corporation - American Depositary Shares|Q|N|N|100|N|N",
        ]
    )

    rows = parse_nasdaq_listed(text)

    assert [row.ticker for row in rows] == ["ARGX", "BNTX", "GMAB", "LEGN"]
    assert {row.asset_type for row in rows} == {"common_stock"}


def test_parse_nasdaq_listed_filters_preferred_depositary_notes_and_funds():
    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "MNSBP|MainStreet Bancshares Inc. Preferred Depositary Shares|Q|N|N|100|N|N",
            "WAFDP|WaFd Inc. Preferred Stock|Q|N|N|100|N|N",
            "SENIOR|Example Corp 5.50% Senior Notes due 2030|Q|N|N|100|N|N",
            "CEF|Example Closed-End Fund|Q|N|N|100|N|N",
            "FUND|Example Income Fund|Q|N|N|100|N|N",
            "TRP|Example Trust Preferred Securities|Q|N|N|100|N|N",
            "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
        ]
    )

    rows = parse_nasdaq_listed(text)

    assert [row.ticker for row in rows] == ["MRNA"]


def test_parse_otherlisted_filters_empty_symbol_dollar_preferreds_and_missing_exchange():
    from src.data_ingestion.nasdaq_trader import parse_otherlisted

    text = "\n".join(
        [
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
            "|Blank Symbol Corp Common Stock|N||N|100|N|",
            "EQH$A|Equitable Holdings Inc Depositary Shares|N|EQH$A|N|100|N|EQH-A",
            "MET$E|MetLife Inc Preferred Series E|N|MET$E|N|100|N|MET-E",
            "TFC$I|Truist Financial Corporation Depositary Shares|N|TFC$I|N|100|N|TFC-I",
            "GOOD|Good Biotech Inc Common Stock||GOOD|N|100|N|GOOD",
            "ODD|Odd Exchange Inc Common Stock|X|ODD|N|100|N|ODD",
        ]
    )

    rows = parse_otherlisted(text)

    assert [(row.ticker, row.exchange) for row in rows] == [("ODD", "X")]
