from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO

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

_SYMBOL_EXCLUSION_TOKENS = (".W", ".U", ".R", ".P", "-W", "-U", "-R", "-P")
_NAME_EXCLUSION_WORDS = (
    " WARRANT",
    " WARRANTS",
    " RIGHT",
    " RIGHTS",
    " UNIT",
    " UNITS",
    " PREFERRED",
    " PREFERENCE",
    " PFD",
)


def parse_nasdaq_listed(text: str) -> list[UniverseSourceRow]:
    rows = []
    for row in _dict_rows(text):
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
    for row in _dict_rows(text):
        symbol = row.get("ACT Symbol", "")
        name = row.get("Security Name", "")
        if _skip_row(
            symbol=symbol,
            name=name,
            etf=row.get("ETF"),
            test_issue=row.get("Test Issue"),
        ):
            continue
        exchange_code = row.get("Exchange", "").strip().upper()
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


def _dict_rows(text: str) -> Iterable[dict[str, str]]:
    cleaned_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.startswith("File Creation Time:")
    ]
    yield from csv.DictReader(StringIO("\n".join(cleaned_lines)), delimiter="|")


def _skip_row(
    *,
    symbol: str,
    name: str,
    etf: str | None,
    test_issue: str | None,
) -> bool:
    upper_symbol = symbol.strip().upper()
    upper_name = name.strip().upper()
    if not upper_symbol:
        return True
    if (test_issue or "").strip().upper() == "Y":
        return True
    if (etf or "").strip().upper() == "Y":
        return True
    if any(token in upper_symbol for token in _SYMBOL_EXCLUSION_TOKENS):
        return True
    if any(word in upper_name for word in _NAME_EXCLUSION_WORDS):
        return True
    return False
