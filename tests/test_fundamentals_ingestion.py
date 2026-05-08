from __future__ import annotations


def test_normalize_fmp_financial_statements_extracts_biotech_burn_fields():
    from src.data_ingestion.fundamentals import normalize_fmp_financial_statements

    rows = normalize_fmp_financial_statements(
        ticker=" mrna ",
        source="fmp_income_balance_cashflow",
        statements=[
            {
                "calendarYear": "2025",
                "period": "Q3",
                "date": "2025-09-30",
                "fillingDate": "2025-11-06",
                "acceptedDate": "2025-11-06 16:05:00",
                "reportedCurrency": "USD",
                "cashAndCashEquivalents": "120.5",
                "shortTermInvestments": 29.5,
                "operatingCashFlow": "-50",
                "researchAndDevelopmentExpenses": "14.25",
                "sellingGeneralAndAdministrativeExpenses": "8.75",
                "revenue": "1000",
                "netIncome": "-22",
                "totalDebt": "12",
            }
        ],
    )

    assert rows == [
        {
            "security_id": "FMP:MRNA",
            "ticker": "MRNA",
            "fiscal_period": "2025-Q3",
            "period_end": "2025-09-30",
            "filing_date": "2025-11-06",
            "accepted_date": "2025-11-06 16:05:00",
            "currency": "USD",
            "cash_and_equivalents": 120.5,
            "short_term_investments": 29.5,
            "cash_and_short_term_investments": 150.0,
            "total_debt": 12.0,
            "operating_cash_flow": -50.0,
            "rd_expense": 14.25,
            "sga_expense": 8.75,
            "revenue": 1000.0,
            "net_income": -22.0,
            "cash_runway_quarters": 3.0,
            "missing_numeric_fields": [],
            "has_missing_numeric_fields": False,
            "source": "fmp_income_balance_cashflow",
        }
    ]
    assert "research_and_development" not in rows[0]
    assert "selling_general_and_administrative" not in rows[0]


def test_normalize_fmp_financial_statements_handles_positive_ocf_and_missing_values():
    from src.data_ingestion.fundamentals import normalize_fmp_financial_statements

    rows = normalize_fmp_financial_statements(
        ticker="jnj",
        source="fmp",
        statements=[
            {
                "calendarYear": "2025",
                "period": "FY",
                "operatingCashFlow": "10",
            }
        ],
    )

    assert rows[0]["ticker"] == "JNJ"
    assert rows[0]["cash_and_equivalents"] == 0.0
    assert rows[0]["short_term_investments"] == 0.0
    assert rows[0]["cash_and_short_term_investments"] == 0.0
    assert rows[0]["rd_expense"] == 0.0
    assert rows[0]["sga_expense"] == 0.0
    assert rows[0]["revenue"] == 0.0
    assert rows[0]["net_income"] == 0.0
    assert rows[0]["total_debt"] == 0.0
    assert rows[0]["missing_numeric_fields"] == [
        "cashAndCashEquivalents",
        "shortTermInvestments",
        "researchAndDevelopmentExpenses",
        "sellingGeneralAndAdministrativeExpenses",
        "revenue",
        "netIncome",
        "totalDebt",
    ]
    assert rows[0]["has_missing_numeric_fields"] is True
    assert rows[0]["cash_runway_quarters"] is None


def test_normalize_fmp_financial_statements_suppresses_runway_when_cash_is_missing():
    from src.data_ingestion.fundamentals import normalize_fmp_financial_statements

    rows = normalize_fmp_financial_statements(
        ticker="MRNA",
        source="fmp",
        statements=[
            {
                "calendarYear": "2025",
                "period": "Q4",
                "shortTermInvestments": "50",
                "operatingCashFlow": "-25",
            }
        ],
    )

    assert rows[0]["cash_and_equivalents"] == 0.0
    assert rows[0]["cash_and_short_term_investments"] == 50.0
    assert rows[0]["operating_cash_flow"] == -25.0
    assert rows[0]["cash_runway_quarters"] is None
    assert "cashAndCashEquivalents" in rows[0]["missing_numeric_fields"]
    assert rows[0]["has_missing_numeric_fields"] is True


def test_normalize_fmp_financial_statements_uses_empty_fiscal_period_fallback():
    from src.data_ingestion.fundamentals import normalize_fmp_financial_statements

    rows = normalize_fmp_financial_statements(
        ticker="MRNA",
        source="fmp",
        statements=[
            {"calendarYear": "2025"},
            {"period": "Q1"},
            {},
        ],
    )

    assert [row["fiscal_period"] for row in rows] == ["", "", ""]


def test_normalize_sec_company_facts_keeps_cik_and_concept_source():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    rows = normalize_sec_company_facts(
        cik=" 12345 ",
        ticker=" lly ",
        companyfacts={
            "facts": {
                "us-gaap": {
                    "ResearchAndDevelopmentExpense": {
                        "units": {
                            "USD": [
                                {
                                    "fy": "2025",
                                    "fp": "Q2",
                                    "form": "10-Q",
                                    "filed": "2025-08-04",
                                    "end": "2025-06-30",
                                    "val": "125.5",
                                }
                            ]
                        }
                    }
                }
            }
        },
    )

    assert rows == [
        {
            "security_id": "SEC:0000012345",
            "ticker": "LLY",
            "cik": "0000012345",
            "taxonomy": "us-gaap",
            "concept": "ResearchAndDevelopmentExpense",
            "unit": "USD",
            "fiscal_year": 2025,
            "fiscal_period": "Q2",
            "form": "10-Q",
            "filed": "2025-08-04",
            "period_end": "2025-06-30",
            "value": 125.5,
            "missing_numeric_fields": [],
            "has_missing_numeric_fields": False,
            "source": "sec_companyfacts",
        }
    ]


def test_normalize_sec_company_facts_converts_missing_value_to_zero():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    rows = normalize_sec_company_facts(
        cik="42",
        ticker="abba",
        companyfacts={
            "facts": {
                "us-gaap": {
                    "CashAndCashEquivalentsAtCarryingValue": {
                        "units": {
                            "USD": [
                                {
                                    "fy": "2025",
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-20",
                                    "end": "2025-12-31",
                                }
                            ]
                        }
                    }
                }
            }
        },
    )

    assert rows[0]["fiscal_period"] == "FY"
    assert rows[0]["value"] == 0.0
    assert rows[0]["missing_numeric_fields"] == ["val"]
    assert rows[0]["has_missing_numeric_fields"] is True


def test_normalize_sec_company_facts_skips_missing_or_invalid_fiscal_year():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    rows = normalize_sec_company_facts(
        cik="42",
        ticker="ABBA",
        companyfacts={
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"fp": "FY", "val": "1.0"},
                                {"fy": "not-a-year", "fp": "FY", "val": "2.0"},
                                {"fy": "2025", "fp": "FY", "val": "3.0"},
                            ]
                        }
                    }
                }
            }
        },
    )

    assert [row["fiscal_year"] for row in rows] == [2025]
    assert [row["value"] for row in rows] == [3.0]


def test_normalize_sec_company_facts_uses_empty_strings_for_missing_strings():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    rows = normalize_sec_company_facts(
        cik="42",
        ticker="ABBA",
        companyfacts={
            "facts": {
                "us-gaap": {
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {
                                    "fy": "2025",
                                    "val": "12.5",
                                }
                            ]
                        }
                    }
                }
            }
        },
    )

    assert rows[0]["fiscal_period"] == ""
    assert rows[0]["form"] == ""
    assert rows[0]["filed"] == ""
    assert rows[0]["period_end"] == ""


def test_normalize_sec_company_facts_ignores_malformed_fact_shapes():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    assert (
        normalize_sec_company_facts(
            cik="42", ticker="ABBA", companyfacts={"facts": ["not", "a", "mapping"]}
        )
        == []
    )
    assert (
        normalize_sec_company_facts(
            cik="42",
            ticker="ABBA",
            companyfacts={
                "facts": {
                    "us-gaap": {
                        "NetIncomeLoss": {"units": {"USD": {"not": "a list"}}}
                    }
                }
            },
        )
        == []
    )


def test_normalize_sec_company_facts_returns_empty_list_for_empty_facts():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    assert normalize_sec_company_facts(cik="1", ticker="MRNA", companyfacts={}) == []
    assert (
        normalize_sec_company_facts(
            cik="1", ticker="MRNA", companyfacts={"facts": {"us-gaap": {}}}
        )
        == []
    )


def test_initialize_research_database_creates_fundamentals_catalog_columns(tmp_path):
    from src.backtest.research_db import initialize_research_database

    db_path = tmp_path / "research.duckdb"
    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        fundamentals_columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(fundamentals_normalized)"
            ).fetchall()
        ]
        sec_columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(sec_companyfacts_normalized)"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert fundamentals_columns == [
        "security_id",
        "ticker",
        "fiscal_period",
        "filing_date",
        "source",
        "payload_json",
        "created_at",
    ]
    assert sec_columns == [
        "security_id",
        "ticker",
        "cik",
        "taxonomy",
        "concept",
        "unit",
        "fiscal_year",
        "fiscal_period",
        "form",
        "filed",
        "period_end",
        "value",
        "source",
        "created_at",
    ]
