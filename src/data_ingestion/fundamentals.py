from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _normalized_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _fiscal_period(statement: Mapping[str, Any]) -> str:
    calendar_year = statement.get("calendarYear")
    period = statement.get("period")
    if calendar_year and period:
        return f"{calendar_year}-{period}"
    return ""


def normalize_fmp_financial_statements(
    *, ticker: str, statements: Iterable[Mapping[str, Any]], source: str
) -> list[dict[str, Any]]:
    normalized_ticker = _normalized_ticker(ticker)
    rows: list[dict[str, Any]] = []

    for statement in statements:
        cash_and_equivalents = _to_float(statement.get("cashAndCashEquivalents"))
        short_term_investments = _to_float(statement.get("shortTermInvestments"))
        cash_and_investments = cash_and_equivalents + short_term_investments
        operating_cash_flow = _to_float(statement.get("operatingCashFlow"))
        cash_runway_quarters = (
            round(cash_and_investments / abs(operating_cash_flow), 6)
            if operating_cash_flow < 0
            else None
        )

        rows.append(
            {
                "security_id": f"FMP:{normalized_ticker}",
                "ticker": normalized_ticker,
                "fiscal_period": _fiscal_period(statement),
                "period_end": statement.get("date"),
                "filing_date": statement.get("fillingDate")
                or statement.get("filingDate"),
                "accepted_date": statement.get("acceptedDate"),
                "currency": statement.get("reportedCurrency"),
                "cash_and_equivalents": cash_and_equivalents,
                "short_term_investments": short_term_investments,
                "cash_and_short_term_investments": cash_and_investments,
                "total_debt": _to_float(statement.get("totalDebt")),
                "operating_cash_flow": operating_cash_flow,
                "rd_expense": _to_float(statement.get("researchAndDevelopmentExpenses")),
                "sga_expense": _to_float(
                    statement.get("sellingGeneralAndAdministrativeExpenses")
                ),
                "revenue": _to_float(statement.get("revenue")),
                "net_income": _to_float(statement.get("netIncome")),
                "cash_runway_quarters": cash_runway_quarters,
                "source": source,
            }
        )

    return rows


def normalize_sec_company_facts(
    *, cik: str, ticker: str, companyfacts: Mapping[str, Any]
) -> list[dict[str, Any]]:
    normalized_ticker = _normalized_ticker(ticker)
    cik10 = cik.strip().zfill(10)
    rows: list[dict[str, Any]] = []

    facts = companyfacts.get("facts") or {}
    for taxonomy, concepts in facts.items():
        for concept, concept_payload in concepts.items():
            units = concept_payload.get("units") or {}
            for unit, values in units.items():
                for value in values:
                    rows.append(
                        {
                            "security_id": f"SEC:{cik10}",
                            "ticker": normalized_ticker,
                            "cik": cik10,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "fiscal_year": int(value.get("fy")),
                            "fiscal_period": str(value.get("fp")),
                            "form": value.get("form"),
                            "filed": value.get("filed"),
                            "period_end": value.get("end"),
                            "value": _to_float(value.get("val")),
                            "source": "sec_companyfacts",
                        }
                    )

    return rows
