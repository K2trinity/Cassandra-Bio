"""Ticker normalization and company metadata for K-line workspaces."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
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
        aliases=["Vertex", "Vertex Pharmaceuticals"],
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

_LEGAL_ENTITY_SUFFIX_RE = re.compile(
    r"\b(?:incorporated|inc|corp|corporation|ltd|limited|plc|llc|company|co|ag|sa|nv)\b",
    flags=re.IGNORECASE,
)


class TickerResolver:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else None

    def normalize(self, value: object) -> str | None:
        ticker = str(value or "").strip().upper()
        if not ticker or "/" in ticker or "\\" in ticker:
            return None
        if not TICKER_PATTERN.fullmatch(ticker):
            return None
        return ticker

    def resolve(self, value: object) -> KlineCompany:
        raw_value = str(value or "").strip()
        if "/" in raw_value or "\\" in raw_value:
            raise ValueError("invalid ticker: use 1-16 letters, numbers, dots, or hyphens")

        universe = self._company_map()
        ticker = self.normalize(value)
        if ticker is None:
            company = _resolve_company_in_map(value, universe)
            if company is not None:
                return _copy_company(company)
            raise ValueError("invalid ticker: use 1-16 letters, numbers, dots, or hyphens")

        company = universe.get(ticker)
        if company is not None:
            return _copy_company(company)

        company = _resolve_company_in_map(value, universe)
        if company is not None:
            return _copy_company(company)

        return KlineCompany(ticker=ticker, name=ticker)

    def list_universe(self) -> list[KlineCompany]:
        universe = self._company_map()
        return [_copy_company(universe[ticker]) for ticker in sorted(universe)]

    def resolve_company_in_universe(self, value: object) -> KlineCompany | None:
        """Resolve a company name or alias only when it exists in the K-line universe."""
        company = _resolve_company_in_map(value, self._company_map())
        return _copy_company(company) if company is not None else None

    def _company_map(self) -> dict[str, KlineCompany]:
        research_universe = _load_research_universe(self.db_path)
        if not research_universe:
            return {ticker: _copy_company(company) for ticker, company in _UNIVERSE.items()}
        return research_universe


def _copy_company(company: KlineCompany) -> KlineCompany:
    return replace(company, aliases=list(company.aliases))


def _company_lookup_key(value: object) -> str:
    text = str(value or "").replace("&", " and ").lower()
    words = re.findall(r"[a-z0-9]+", text)
    filtered = [word for word in words if not _LEGAL_ENTITY_SUFFIX_RE.fullmatch(word)]
    return " ".join(filtered).strip()


def _resolve_company_in_map(
    value: object,
    universe: dict[str, KlineCompany],
) -> KlineCompany | None:
    normalized_value = _company_lookup_key(value)
    if not normalized_value:
        return None

    exact_matches: dict[str, KlineCompany] = {}
    prefix_matches: dict[str, KlineCompany] = {}
    for company in universe.values():
        candidates = [company.ticker, company.name, *company.aliases]
        for candidate in candidates:
            key = _company_lookup_key(candidate)
            if key == normalized_value:
                exact_matches[company.ticker] = company
            elif _is_unique_name_prefix(normalized_value, key):
                prefix_matches[company.ticker] = company

    matches = exact_matches or prefix_matches
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def _is_unique_name_prefix(query: str, candidate: str) -> bool:
    if len(query) < 3 or not candidate.startswith(query):
        return False
    return len(candidate) == len(query) or candidate[len(query)] == " "


def _load_research_universe(db_path: Path | None) -> dict[str, KlineCompany]:
    path = db_path or _default_research_db_path()
    if not path.exists():
        return {}

    import duckdb

    try:
        conn = duckdb.connect(str(path), read_only=True)
    except duckdb.Error:
        return {}
    try:
        row = conn.execute(
            """
            SELECT source_payload_json
            FROM universe_snapshots
            WHERE universe_id = 'biotech_us_v1'
            ORDER BY as_of_date DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
    except duckdb.Error:
        return {}
    finally:
        conn.close()
    if row is None:
        return {}

    try:
        payloads = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return {}

    companies: dict[str, KlineCompany] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        asset_type = str(payload.get("asset_type") or "").strip().lower().replace("_", " ")
        if asset_type not in {"common stock", "common", "stock", "equity"}:
            continue
        ticker = str(payload.get("ticker") or "").strip().upper()
        if not TICKER_PATTERN.fullmatch(ticker):
            continue
        static_company = _UNIVERSE.get(ticker)
        industry = str(payload.get("industry") or "")
        name = str(payload.get("company_name") or "").strip() or ticker
        companies[ticker] = KlineCompany(
            ticker=ticker,
            name=name,
            aliases=list(static_company.aliases) if static_company else [],
            sector="Healthcare",
            is_biotech=(
                bool(static_company and static_company.is_biotech)
                or "biotech" in industry.lower()
                or "pharmaceutical" in industry.lower()
            ),
        )
    return companies


def _default_research_db_path() -> Path:
    from src.backtest.research_db import RESEARCH_DB_PATH

    return Path(RESEARCH_DB_PATH)
