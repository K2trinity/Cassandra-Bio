from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO
import re

from src.backtest.universe_builder import UniverseSourceRow

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

_OTHER_EXCHANGES = {
    "A": "NYSEAMERICAN",
    "N": "NYSE",
    "P": "NYSEARCA",
    "Z": "BATS",
    "V": "IEX",
}

_NASDAQ_LISTED_REQUIRED_COLUMNS = frozenset(
    {
        "Symbol",
        "Security Name",
        "Test Issue",
        "ETF",
    }
)
_OTHERLISTED_REQUIRED_COLUMNS = frozenset(
    {
        "ACT Symbol",
        "Security Name",
        "Exchange",
        "ETF",
        "Test Issue",
    }
)
_SYMBOL_EXCLUSION_TOKENS = (".W", ".U", ".R", ".P", "-W", "-U", "-R", "-P")
_NAME_EXCLUSION_PATTERNS = (
    re.compile(r"\bWARRANTS?\b"),
    re.compile(r"\bRIGHTS?\b"),
    re.compile(r"\bUNITS?\b"),
    re.compile(r"\bPREFERRED\b"),
    re.compile(r"\bPREFERENCE\b"),
    re.compile(r"\bPFD\b"),
    re.compile(r"\bDEPOSITARY\b"),
    re.compile(r"\bSENIOR\s+NOTES?\b"),
    re.compile(r"\bNOTES?\s+DUE\b"),
    re.compile(r"\bCLOSED[- ]END\s+FUND\b"),
    re.compile(r"\bFUNDS?\b"),
    re.compile(r"\bTRUST\s+PREFERRED\b"),
)


def parse_nasdaq_listed(text: str) -> list[UniverseSourceRow]:
    rows = []
    for row in _dict_rows(
        text,
        required_columns=_NASDAQ_LISTED_REQUIRED_COLUMNS,
        source_name="Nasdaq listed",
    ):
        symbol = row.get("Symbol", "")
        name = row.get("Security Name", "")
        if _skip_row(
            symbol=symbol,
            name=name,
            etf=row.get("ETF"),
            test_issue=row.get("Test Issue"),
        ):
            continue
        rows.append(
            UniverseSourceRow(
                ticker=symbol.strip().upper(),
                company_name=name.strip(),
                exchange="NASDAQ",
                asset_type="common_stock",
                source="exchange_listings",
            )
        )
    return rows


def parse_otherlisted(text: str) -> list[UniverseSourceRow]:
    rows = []
    for row in _dict_rows(
        text,
        required_columns=_OTHERLISTED_REQUIRED_COLUMNS,
        source_name="other listed",
    ):
        symbol = row.get("ACT Symbol", "")
        name = row.get("Security Name", "")
        exchange_code = row.get("Exchange", "").strip().upper()
        if _skip_row(
            symbol=symbol,
            name=name,
            etf=row.get("ETF"),
            test_issue=row.get("Test Issue"),
            exchange=exchange_code,
        ):
            continue
        rows.append(
            UniverseSourceRow(
                ticker=symbol.strip().upper(),
                company_name=name.strip(),
                exchange=_OTHER_EXCHANGES.get(exchange_code, exchange_code),
                asset_type="common_stock",
                source="exchange_listings",
            )
        )
    return rows


def parse_symbol_directories(
    *,
    nasdaqlisted_text: str,
    otherlisted_text: str,
) -> list[UniverseSourceRow]:
    return [
        *parse_nasdaq_listed(nasdaqlisted_text),
        *parse_otherlisted(otherlisted_text),
    ]


def _dict_rows(
    text: str,
    *,
    required_columns: frozenset[str],
    source_name: str,
) -> Iterable[dict[str, str]]:
    cleaned_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("File Creation Time:")
    ]
    reader = csv.DictReader(StringIO("\n".join(cleaned_lines)), delimiter="|")
    fieldnames = set(reader.fieldnames or [])
    missing_columns = sorted(required_columns - fieldnames)
    if missing_columns:
        raise ValueError(
            f"Missing required {source_name} columns: {', '.join(missing_columns)}"
        )
    yield from reader


def _skip_row(
    *,
    symbol: str,
    name: str,
    etf: str | None,
    test_issue: str | None,
    exchange: str | None = "NASDAQ",
) -> bool:
    upper_symbol = symbol.strip().upper()
    upper_name = name.strip().upper()
    if not upper_symbol:
        return True
    if not (exchange or "").strip():
        return True
    if (test_issue or "").strip().upper() == "Y":
        return True
    if (etf or "").strip().upper() == "Y":
        return True
    if "$" in upper_symbol:
        return True
    if any(token in upper_symbol for token in _SYMBOL_EXCLUSION_TOKENS):
        return True
    if any(pattern.search(upper_name) for pattern in _NAME_EXCLUSION_PATTERNS):
        return True
    return False
