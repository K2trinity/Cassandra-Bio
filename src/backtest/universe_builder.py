from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Any


BIOTECH_US_UNIVERSE_ID = "biotech_us_v1"
BIOTECH_UNIVERSE_ID = BIOTECH_US_UNIVERSE_ID
BIOTECH_BIAS_STATUS = "current_constituents_only"

_CANONICAL_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_COMMON_STOCK_TYPES = {
    "common stock",
    "common_stock",
    "common",
    "stock",
    "equity",
}
_BENCHMARK_ASSET_TYPES = {
    "etf",
    "fund",
    "mutual fund",
    "mutual_fund",
    "exchange traded fund",
    "exchange_traded_fund",
}


@dataclass(frozen=True)
class UniverseSourceRow:
    ticker: str
    company_name: str
    exchange: str
    asset_type: str
    source: str
    source_weight: float | None = None
    industry: str | None = None
    cik: str | None = None
    cusip: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class UniverseMember:
    ticker: str
    company_name: str
    exchange: str
    asset_type: str
    source_memberships: tuple[str, ...]
    source_weights: dict[str, float]
    industry: str | None = None
    cik: str | None = None
    cusip: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_snapshot_id: str
    universe_id: str
    as_of_date: str
    members: tuple[UniverseMember, ...]
    benchmark_tickers: tuple[str, ...]
    sources: tuple[str, ...]
    bias_status: str = BIOTECH_BIAS_STATUS
    survivorship_bias_warning: bool = True

    def to_catalog_payload(self) -> dict[str, Any]:
        source_payload = [{"source": source} for source in self.sources]
        return {
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_id": self.universe_id,
            "as_of_date": self.as_of_date,
            "bias_status": self.bias_status,
            "survivorship_bias_warning": self.survivorship_bias_warning,
            "member_count": len(self.members),
            "benchmark_tickers_json": _canonical_json(list(self.benchmark_tickers)),
            "source_payload_json": _canonical_json(source_payload),
            "coverage_json": _canonical_json(
                {
                    "benchmark_tickers": list(self.benchmark_tickers),
                    "member_count": len(self.members),
                    "sources": list(self.sources),
                }
            ),
        }


def build_universe_snapshot(
    rows: list[UniverseSourceRow] | tuple[UniverseSourceRow, ...],
    *,
    as_of_date: str | date | datetime,
) -> UniverseSnapshot:
    canonical_date = _canonical_as_of_date(as_of_date)
    members_by_ticker: dict[str, dict[str, Any]] = {}
    benchmark_tickers: set[str] = set()
    sources: set[str] = set()

    for row in rows:
        ticker = _normalize_ticker(row.ticker)
        source = _normalize_source(row.source)
        asset_type = _normalize_asset_type(row.asset_type)
        sources.add(source)

        if asset_type in _BENCHMARK_ASSET_TYPES:
            benchmark_tickers.add(ticker)
            continue
        if asset_type not in _COMMON_STOCK_TYPES:
            continue

        member = members_by_ticker.setdefault(
            ticker,
            {
                "ticker": ticker,
                "company_name": row.company_name,
                "exchange": _normalize_exchange(row.exchange),
                "asset_type": "common_stock",
                "source_memberships": set(),
                "source_weights": {},
                "industry": row.industry,
                "cik": row.cik,
                "cusip": row.cusip,
                "isin": row.isin,
            },
        )
        member["source_memberships"].add(source)
        if row.source_weight is not None:
            member["source_weights"][source] = row.source_weight
        for field_name in ("industry", "cik", "cusip", "isin"):
            if member[field_name] is None and getattr(row, field_name) is not None:
                member[field_name] = getattr(row, field_name)

    members = tuple(
        UniverseMember(
            ticker=member["ticker"],
            company_name=member["company_name"],
            exchange=member["exchange"],
            asset_type=member["asset_type"],
            source_memberships=tuple(sorted(member["source_memberships"])),
            source_weights=dict(sorted(member["source_weights"].items())),
            industry=member["industry"],
            cik=member["cik"],
            cusip=member["cusip"],
            isin=member["isin"],
        )
        for member in sorted(members_by_ticker.values(), key=lambda item: item["ticker"])
    )
    benchmark_tuple = tuple(sorted(benchmark_tickers))
    source_tuple = tuple(sorted(sources))
    snapshot_id = _build_universe_snapshot_id(
        as_of_date=canonical_date,
        members=members,
        benchmark_tickers=benchmark_tuple,
        sources=source_tuple,
    )

    return UniverseSnapshot(
        universe_snapshot_id=snapshot_id,
        universe_id=BIOTECH_UNIVERSE_ID,
        as_of_date=canonical_date,
        members=members,
        benchmark_tickers=benchmark_tuple,
        sources=source_tuple,
    )


def _build_universe_snapshot_id(
    *,
    as_of_date: str,
    members: tuple[UniverseMember, ...],
    benchmark_tickers: tuple[str, ...],
    sources: tuple[str, ...],
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "benchmark_tickers": benchmark_tickers,
        "bias_status": BIOTECH_BIAS_STATUS,
        "members": [
            {
                "ticker": member.ticker,
                "company_name": member.company_name,
                "exchange": member.exchange,
                "asset_type": member.asset_type,
                "source_memberships": member.source_memberships,
                "source_weights": member.source_weights,
                "industry": member.industry,
                "cik": member.cik,
                "cusip": member.cusip,
                "isin": member.isin,
            }
            for member in members
        ],
        "sources": sources,
        "survivorship_bias_warning": True,
        "universe_id": BIOTECH_US_UNIVERSE_ID,
    }
    digest = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    return f"univ_{as_of_date.replace('-', '')}_{digest}"


def _canonical_as_of_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        if not _CANONICAL_DATE_RE.fullmatch(value):
            raise ValueError("as_of_date string must use canonical YYYY-MM-DD format")
        return date.fromisoformat(value).isoformat()
    raise ValueError("as_of_date must be a YYYY-MM-DD string, date, or datetime")


def _normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def _normalize_source(value: str) -> str:
    source = value.strip().lower()
    if not source:
        raise ValueError("source is required")
    return source


def _normalize_exchange(value: str) -> str:
    return value.strip().upper()


def _normalize_asset_type(value: str) -> str:
    return value.strip().lower().replace("-", " ")


def _json_ready(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_ready(nested_value) for nested_value in value]
    if isinstance(value, list):
        return [_json_ready(nested_value) for nested_value in value]
    if isinstance(value, dict):
        return {
            key: _json_ready(nested_value)
            for key, nested_value in sorted(value.items())
        }
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
