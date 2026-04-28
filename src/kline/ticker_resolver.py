"""Ticker normalization and company metadata for K-line workspaces."""

from __future__ import annotations

import re

from src.kline.models import KlineCompany


TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")


_UNIVERSE: dict[str, KlineCompany] = {
    "MRNA": KlineCompany(
        ticker="MRNA",
        name="Moderna, Inc.",
        aliases=["ModernaTX, Inc.", "ModernaTX"],
        is_biotech=True,
    ),
    "BIIB": KlineCompany(
        ticker="BIIB",
        name="Biogen Inc.",
        aliases=["Biogen"],
        is_biotech=True,
    ),
    "VRTX": KlineCompany(
        ticker="VRTX",
        name="Vertex Pharmaceuticals Incorporated",
        aliases=["Vertex Pharmaceuticals"],
        is_biotech=True,
    ),
    "REGN": KlineCompany(
        ticker="REGN",
        name="Regeneron Pharmaceuticals, Inc.",
        aliases=["Regeneron"],
        is_biotech=True,
    ),
    "GILD": KlineCompany(
        ticker="GILD",
        name="Gilead Sciences, Inc.",
        aliases=["Gilead"],
        is_biotech=True,
    ),
    "AMGN": KlineCompany(
        ticker="AMGN",
        name="Amgen Inc.",
        aliases=["Amgen"],
        is_biotech=True,
    ),
    "BMY": KlineCompany(
        ticker="BMY",
        name="Bristol-Myers Squibb Company",
        aliases=["Bristol Myers Squibb"],
    ),
    "PFE": KlineCompany(
        ticker="PFE",
        name="Pfizer Inc.",
        aliases=["Pfizer"],
    ),
    "LLY": KlineCompany(
        ticker="LLY",
        name="Eli Lilly and Company",
        aliases=["Eli Lilly"],
    ),
    "CRSP": KlineCompany(
        ticker="CRSP",
        name="CRISPR Therapeutics AG",
        aliases=["CRISPR Therapeutics"],
        is_biotech=True,
    ),
    "NTLA": KlineCompany(
        ticker="NTLA",
        name="Intellia Therapeutics, Inc.",
        aliases=["Intellia Therapeutics"],
        is_biotech=True,
    ),
    "BEAM": KlineCompany(
        ticker="BEAM",
        name="Beam Therapeutics Inc.",
        aliases=["Beam Therapeutics"],
        is_biotech=True,
    ),
}


class TickerResolver:
    def normalize(self, value: object) -> str | None:
        ticker = str(value or "").strip().upper()
        if not ticker or "/" in ticker or "\\" in ticker:
            return None
        if not TICKER_PATTERN.fullmatch(ticker):
            return None
        return ticker

    def resolve(self, value: object) -> KlineCompany:
        ticker = self.normalize(value)
        if ticker is None:
            raise ValueError("invalid ticker: use 1-16 letters, numbers, dots, or hyphens")

        company = _UNIVERSE.get(ticker)
        if company is not None:
            return company

        return KlineCompany(ticker=ticker, name=ticker)

    def list_universe(self) -> list[KlineCompany]:
        return [_UNIVERSE[ticker] for ticker in sorted(_UNIVERSE)]
