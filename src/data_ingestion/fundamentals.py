from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _normalized_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _is_missing_numeric(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        float(value)
    except (TypeError, ValueError):
        return True
    return False


def _to_float(value: Any) -> float:
    if _is_missing_numeric(value):
        return 0.0
    return float(value)


def _missing_fields(payload: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if _is_missing_numeric(payload.get(field))]


def _fiscal_period(statement: Mapping[str, Any]) -> str:
    calendar_year = statement.get("calendarYear")
    period = statement.get("period")
    if calendar_year and period:
        return f"{calendar_year}-{period}"
    return ""


def _to_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


FMP_NUMERIC_FIELDS: tuple[str, ...] = (
    "cashAndCashEquivalents",
    "shortTermInvestments",
    "operatingCashFlow",
    "researchAndDevelopmentExpenses",
    "sellingGeneralAndAdministrativeExpenses",
    "revenue",
    "netIncome",
    "totalDebt",
)

FMP_RUNWAY_INPUT_FIELDS: tuple[str, ...] = (
    "cashAndCashEquivalents",
    "shortTermInvestments",
    "operatingCashFlow",
)


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
        missing_numeric_fields = _missing_fields(statement, FMP_NUMERIC_FIELDS)
        missing_runway_input = any(
            field in missing_numeric_fields for field in FMP_RUNWAY_INPUT_FIELDS
        )
        cash_runway_quarters = (
            round(cash_and_investments / abs(operating_cash_flow), 6)
            if operating_cash_flow < 0 and not missing_runway_input
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
                "missing_numeric_fields": missing_numeric_fields,
                "has_missing_numeric_fields": bool(missing_numeric_fields),
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
    if not isinstance(facts, Mapping):
        return rows

    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, Mapping):
            continue
        for concept, concept_payload in concepts.items():
            if not isinstance(concept_payload, Mapping):
                continue
            units = concept_payload.get("units") or {}
            if not isinstance(units, Mapping):
                continue
            for unit, values in units.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, Mapping):
                        continue
                    fiscal_year = _to_int_or_none(value.get("fy"))
                    if fiscal_year is None:
                        continue
                    missing_numeric_fields = _missing_fields(value, ("val",))
                    rows.append(
                        {
                            "security_id": f"SEC:{cik10}",
                            "ticker": normalized_ticker,
                            "cik": cik10,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "fiscal_year": fiscal_year,
                            "fiscal_period": _string_or_empty(value.get("fp")),
                            "form": _string_or_empty(value.get("form")),
                            "filed": _string_or_empty(value.get("filed")),
                            "period_end": _string_or_empty(value.get("end")),
                            "value": _to_float(value.get("val")),
                            "missing_numeric_fields": missing_numeric_fields,
                            "has_missing_numeric_fields": bool(missing_numeric_fields),
                            "source": "sec_companyfacts",
                        }
                    )

    return rows
