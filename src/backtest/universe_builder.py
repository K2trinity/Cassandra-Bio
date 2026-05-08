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
    "benchmark_etf",
    "fund",
    "mutual fund",
    "mutual_fund",
    "exchange traded fund",
    "exchange_traded_fund",
}
_SOURCE_PRECEDENCE = {
    "exchange_listings": 0,
    "nasdaq_screener": 0,
    "nyse": 0,
    "ibb": 1,
    "xbi": 2,
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
    security_id: str
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
    source_payloads: tuple[dict[str, Any], ...]
    bias_status: str = BIOTECH_BIAS_STATUS
    survivorship_bias_warning: bool = True

    def to_catalog_payload(self) -> dict[str, Any]:
        return {
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_id": self.universe_id,
            "as_of_date": self.as_of_date,
            "bias_status": self.bias_status,
            "survivorship_bias_warning": self.survivorship_bias_warning,
            "member_count": len(self.members),
            "benchmark_tickers_json": _canonical_json(list(self.benchmark_tickers)),
            "source_payload_json": _canonical_json(list(self.source_payloads)),
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
    rows_by_member_ticker: dict[str, list[dict[str, Any]]] = {}
    benchmark_tickers: set[str] = set()
    sources: set[str] = set()
    source_payloads: list[dict[str, Any]] = []

    for row in rows:
        ticker = _normalize_ticker(row.ticker)
        source = _normalize_source(row.source)
        asset_type = _normalize_asset_type(row.asset_type)
        sources.add(source)
        row_payload = _row_payload(
            row,
            ticker=ticker,
            source=source,
            asset_type=asset_type,
        )
        source_payloads.append(row_payload)

        if asset_type in _BENCHMARK_ASSET_TYPES:
            benchmark_tickers.add(ticker)
            continue
        if asset_type not in _COMMON_STOCK_TYPES:
            continue
        rows_by_member_ticker.setdefault(ticker, []).append(row_payload)

    members = tuple(
        _build_member_from_rows(ticker, candidate_rows)
        for ticker, candidate_rows in sorted(rows_by_member_ticker.items())
    )
    benchmark_tuple = tuple(sorted(benchmark_tickers))
    source_tuple = tuple(sorted(sources))
    source_payload_tuple = tuple(sorted(source_payloads, key=_source_payload_sort_key))
    snapshot_id = _build_universe_snapshot_id(
        as_of_date=canonical_date,
        members=members,
        benchmark_tickers=benchmark_tuple,
        sources=source_tuple,
        source_payloads=source_payload_tuple,
    )

    return UniverseSnapshot(
        universe_snapshot_id=snapshot_id,
        universe_id=BIOTECH_UNIVERSE_ID,
        as_of_date=canonical_date,
        members=members,
        benchmark_tickers=benchmark_tuple,
        sources=source_tuple,
        source_payloads=source_payload_tuple,
    )


def _build_universe_snapshot_id(
    *,
    as_of_date: str,
    members: tuple[UniverseMember, ...],
    benchmark_tickers: tuple[str, ...],
    sources: tuple[str, ...],
    source_payloads: tuple[dict[str, Any], ...],
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "benchmark_tickers": benchmark_tickers,
        "bias_status": BIOTECH_BIAS_STATUS,
        "members": [
            {
                "security_id": member.security_id,
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
        "source_payloads": source_payloads,
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
    asset_type = value.strip().lower().replace("-", " ")
    if asset_type == "common_stock":
        return "common stock"
    if asset_type == "mutual_fund":
        return "mutual fund"
    return asset_type


def _source_rank(source: str) -> tuple[int, str]:
    return (_SOURCE_PRECEDENCE.get(source, 100), source)


def _member_row_sort_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _source_rank(payload["source"]),
        payload["ticker"],
        payload["company_name"],
        payload["exchange"],
        _canonical_json(payload),
    )


def _build_member_from_rows(
    ticker: str,
    candidate_rows: list[dict[str, Any]],
) -> UniverseMember:
    sorted_rows = sorted(candidate_rows, key=_member_row_sort_key)
    primary = sorted_rows[0]
    return UniverseMember(
        security_id=f"BIO:{ticker}",
        ticker=ticker,
        company_name=primary["company_name"],
        exchange=primary["exchange"],
        asset_type="common_stock",
        source_memberships=tuple(sorted({row["source"] for row in sorted_rows})),
        source_weights=_source_weights_from_rows(sorted_rows),
        industry=_first_non_empty(sorted_rows, "industry"),
        cik=_first_non_empty(sorted_rows, "cik"),
        cusip=_first_non_empty(sorted_rows, "cusip"),
        isin=_first_non_empty(sorted_rows, "isin"),
    )


def _source_weights_from_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        if row["source_weight"] is not None and row["source"] not in weights:
            weights[row["source"]] = row["source_weight"]
    return dict(sorted(weights.items()))


def _first_non_empty(rows: list[dict[str, Any]], field_name: str) -> Any:
    for row in rows:
        if row[field_name] is not None:
            return row[field_name]
    return None


def _row_payload(
    row: UniverseSourceRow,
    *,
    ticker: str,
    source: str,
    asset_type: str,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_name": row.company_name,
        "exchange": _normalize_exchange(row.exchange),
        "asset_type": asset_type,
        "source": source,
        "source_weight": row.source_weight,
        "industry": row.industry,
        "cik": row.cik,
        "cusip": row.cusip,
        "isin": row.isin,
    }


def _source_payload_sort_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        payload["ticker"],
        payload["source"],
        payload["asset_type"],
        payload["company_name"],
        _canonical_json(payload),
    )


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
