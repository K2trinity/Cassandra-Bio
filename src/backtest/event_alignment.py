from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.backtest.research_db import RESEARCH_DIR

EVENT_PRICE_LINK_COLUMNS = [
    "data_snapshot_id",
    "security_id",
    "event_id",
    "event_date",
    "event_timestamp_utc",
    "release_session",
    "ticker_scope",
    "aligned_signal_date",
    "aligned_trade_date",
    "alignment_rule",
    "price_date_available",
    "created_at",
]

SAFE_PARTITION_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")


def align_events_for_snapshot(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    data_snapshot_id: str,
    security_id: str,
) -> pd.DataFrame:
    data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
    if "date" not in prices.columns:
        raise ValueError("Price frame missing required column: date")

    price_dates = _price_dates(prices)
    created_at = _utc_now_iso()
    rows = []
    for _, event in events.iterrows():
        event_date = _event_date(event)
        timestamp = _optional_text(event.get("event_timestamp_utc"))
        release_session = _optional_text(event.get("release_session"))
        aligned_date, alignment_rule, price_date_available = _align_event(
            event_date=event_date,
            event_timestamp_utc=timestamp,
            release_session=release_session,
            price_dates=price_dates,
        )
        rows.append(
            {
                "data_snapshot_id": data_snapshot_id,
                "security_id": security_id,
                "event_id": _event_id(event),
                "event_date": event_date,
                "event_timestamp_utc": timestamp,
                "release_session": release_session,
                "ticker_scope": _optional_text(event.get("ticker_scope")),
                "aligned_signal_date": aligned_date,
                "aligned_trade_date": aligned_date,
                "alignment_rule": alignment_rule,
                "price_date_available": price_date_available,
                "created_at": created_at,
            }
        )

    return _links_frame(rows)


def write_event_price_links(
    links: pd.DataFrame,
    *,
    output_root: str | Path | None = None,
) -> Path | None:
    if links.empty:
        return None

    missing = set(EVENT_PRICE_LINK_COLUMNS) - set(links.columns)
    if missing:
        raise ValueError(f"Event-price links missing columns: {sorted(missing)}")

    frame = links[EVENT_PRICE_LINK_COLUMNS].copy()
    snapshot_ids = sorted(
        {
            str(value)
            for value in frame["data_snapshot_id"].dropna().unique()
            if str(value).strip()
        }
    )
    if len(snapshot_ids) != 1:
        raise ValueError("Event-price links must contain exactly one data_snapshot_id")

    data_snapshot_id = _safe_partition_token("data_snapshot_id", snapshot_ids[0])
    root = (
        Path(output_root)
        if output_root is not None
        else RESEARCH_DIR / "event_price_links"
    )
    path = root / f"data_snapshot_id={data_snapshot_id}" / "event_price_links.parquet"
    if path.exists():
        raise FileExistsError(f"Event-price links already exist: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def _align_event(
    *,
    event_date: str | None,
    event_timestamp_utc: str | None,
    release_session: str | None,
    price_dates: list[str],
) -> tuple[str | None, str, bool]:
    if event_date is None:
        return None, "invalid_event_date", False

    session = release_session.lower() if release_session else None
    if session == "pre_market":
        target = _next_price_date(price_dates, event_date, strict=False)
        if target is None:
            return None, "outside_price_window", False
        if target == event_date:
            return target, "pre_market_same_trading_day", True
        return target, "pre_market_next_trading_day", True

    if session == "after_close":
        target = _next_price_date(price_dates, event_date, strict=True)
        if target is None:
            return None, "outside_price_window", False
        return target, "after_close_next_trading_day", True

    if event_timestamp_utc is not None:
        target = _next_price_date(price_dates, event_date, strict=True)
        if target is None:
            return None, "outside_price_window", False
        return target, "timestamp_unknown_session_next_trading_day", True

    target = _next_price_date(price_dates, event_date, strict=False)
    if target is None:
        return None, "outside_price_window", False
    return target, "date_only_next_trading_day", True


def _next_price_date(
    price_dates: list[str],
    event_date: str,
    *,
    strict: bool,
) -> str | None:
    for price_date in price_dates:
        matches = price_date > event_date if strict else price_date >= event_date
        if matches:
            return price_date
    return None


def _price_dates(prices: pd.DataFrame) -> list[str]:
    parsed = pd.to_datetime(prices["date"], errors="coerce")
    return sorted(
        {
            value.date().isoformat()
            for value in parsed.dropna()
        }
    )


def _event_date(event: pd.Series) -> str | None:
    for column in ("effective_event_date", "date", "event_timestamp_utc"):
        value = event.get(column)
        date_text = _date_text(value)
        if date_text is not None:
            return date_text
    return None


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _event_id(event: pd.Series) -> str | None:
    return _optional_text(event.get("id")) or _optional_text(event.get("event_id"))


def _optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _links_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=EVENT_PRICE_LINK_COLUMNS)
    if "price_date_available" in frame.columns:
        frame["price_date_available"] = frame["price_date_available"].astype(object)
    return frame


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_partition_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string.")
    if not SAFE_PARTITION_TOKEN.fullmatch(value):
        raise ValueError(f"{name} contains unsupported path characters: {value!r}.")
    return value
