from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from uuid import uuid4

import pandas as pd

from src.backtest.research_db import RESEARCH_DIR

EVENT_PRICE_LINK_COLUMNS = [
    "event_id",
    "security_id",
    "ticker_scope",
    "original_event_date",
    "event_timestamp_utc",
    "release_session",
    "aligned_signal_date",
    "aligned_trade_date",
    "alignment_rule",
    "alignment_confidence",
    "price_date_available",
    "data_snapshot_id",
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
    security_id = _required_text("security_id", security_id)
    if "date" not in prices.columns:
        raise ValueError("Price frame missing required column: date")

    price_dates = _price_dates(prices)
    created_at = _utc_now_iso()
    rows = []
    for _, event in events.iterrows():
        event_id = _event_id(event)
        ticker_scope = _required_text("ticker_scope", event.get("ticker_scope"))
        event_date = _event_date(event)
        timestamp = _event_timestamp_utc(event.get("event_timestamp_utc"))
        release_session = _optional_text(event.get("release_session"))
        (
            aligned_date,
            alignment_rule,
            alignment_confidence,
            price_date_available,
        ) = _align_event(
            event_date=event_date,
            event_timestamp_utc=timestamp,
            release_session=release_session,
            price_dates=price_dates,
        )
        rows.append(
            {
                "event_id": event_id,
                "security_id": security_id,
                "ticker_scope": ticker_scope,
                "original_event_date": event_date,
                "event_timestamp_utc": timestamp,
                "release_session": release_session,
                "aligned_signal_date": aligned_date,
                "aligned_trade_date": aligned_date,
                "alignment_rule": alignment_rule,
                "alignment_confidence": alignment_confidence,
                "price_date_available": price_date_available,
                "data_snapshot_id": data_snapshot_id,
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
    _validate_required_link_columns(frame)
    _normalize_and_validate_aligned_dates(frame)
    snapshot_ids = sorted({str(value) for value in frame["data_snapshot_id"].unique()})
    if len(snapshot_ids) != 1:
        raise ValueError("Event-price links must contain exactly one data_snapshot_id")

    data_snapshot_id = _safe_partition_token("data_snapshot_id", snapshot_ids[0])
    root = (
        Path(output_root)
        if output_root is not None
        else RESEARCH_DIR / "event_price_links"
    )
    partition = root / f"data_snapshot_id={data_snapshot_id}"
    path = partition / "event_price_links.parquet"
    lock_path = partition / "event_price_links.lock"
    temp_path = partition / f"event_price_links.{uuid4().hex}.tmp"

    partition.mkdir(parents=True, exist_ok=True)
    lock_handle = None
    lock_acquired = False
    try:
        try:
            lock_handle = lock_path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise FileExistsError(
                f"Event-price links write lock exists: {lock_path}"
            ) from exc
        lock_acquired = True
        lock_handle.write(_utc_now_iso())
        lock_handle.flush()
        if path.exists():
            raise FileExistsError(f"Event-price links already exist: {path}")
        frame.to_parquet(temp_path, index=False)
        if path.exists():
            raise FileExistsError(f"Event-price links already exist: {path}")
        temp_path.replace(path)
    finally:
        if lock_handle is not None:
            lock_handle.close()
        if temp_path.exists():
            temp_path.unlink()
        if lock_acquired and lock_path.exists():
            lock_path.unlink()
    return path


def _align_event(
    *,
    event_date: str | None,
    event_timestamp_utc: str | None,
    release_session: str | None,
    price_dates: list[str],
) -> tuple[str | None, str, float, bool]:
    if event_date is None:
        return None, "invalid_event_date", 0.0, False

    session = release_session.lower() if release_session else None
    if session == "pre_market":
        target = _next_price_date(price_dates, event_date, strict=False)
        if target is None:
            return None, "outside_price_window", 0.0, False
        if target == event_date:
            return target, "pre_market_same_trading_day", 1.0, True
        return target, "pre_market_next_trading_day", 0.9, True

    if session == "after_close":
        target = _next_price_date(price_dates, event_date, strict=True)
        if target is None:
            return None, "outside_price_window", 0.0, False
        return target, "after_close_next_trading_day", 1.0, True

    if event_timestamp_utc is not None:
        target = _next_price_date(price_dates, event_date, strict=True)
        if target is None:
            return None, "outside_price_window", 0.0, False
        return target, "timestamp_unknown_session_next_trading_day", 0.8, True

    target = _next_price_date(price_dates, event_date, strict=True)
    if target is None:
        return None, "outside_price_window", 0.0, False
    return target, "date_only_next_trading_day", 0.5, True


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
    dates = set()
    for value in prices["date"]:
        date_text = _date_text(
            value,
            field_name="price date",
            raise_invalid_numeric=False,
        )
        if date_text is not None:
            dates.add(date_text)
    return sorted(dates)


def _event_date(event: pd.Series) -> str | None:
    for column in ("effective_event_date", "date"):
        value = event.get(column)
        date_text = _date_text(
            value,
            field_name=column,
            raise_invalid_numeric=True,
        )
        if date_text is not None:
            return date_text
    timestamp = _event_timestamp_utc(event.get("event_timestamp_utc"))
    if timestamp is not None:
        return _date_text(timestamp, field_name="event_timestamp_utc")
    return None


def _date_text(
    value: object,
    *,
    field_name: str = "date",
    raise_invalid_numeric: bool = False,
) -> str | None:
    if value is None or pd.isna(value):
        return None
    if _is_numeric_date_value(value):
        return _numeric_date_text(
            value,
            field_name=field_name,
            raise_invalid=raise_invalid_numeric,
        )
    if isinstance(value, str) and re.fullmatch(r"\d{8}", value.strip()):
        try:
            return datetime.strptime(value.strip(), "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _event_id(event: pd.Series) -> str | None:
    value = _optional_text(event.get("event_id")) or _optional_text(event.get("id"))
    return _required_text("event_id", value)


def _event_timestamp_utc(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _has_time_component(text):
        raise ValueError(
            f"event_timestamp_utc must include a time component: {text!r}"
        )
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"event_timestamp_utc must be a valid timestamp: {text!r}")
    return (
        parsed.to_pydatetime()
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _links_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=EVENT_PRICE_LINK_COLUMNS)
    if "price_date_available" in frame.columns:
        frame["price_date_available"] = frame["price_date_available"].astype(object)
    if "alignment_confidence" in frame.columns:
        frame["alignment_confidence"] = frame["alignment_confidence"].astype("float64")
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


def _required_text(name: str, value: object) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{name} must be a non-empty string.")
    return text


def _validate_required_link_columns(frame: pd.DataFrame) -> None:
    for column in ("event_id", "security_id", "ticker_scope", "data_snapshot_id"):
        for value in frame[column]:
            _required_text(column, value)


def _normalize_and_validate_aligned_dates(frame: pd.DataFrame) -> None:
    for index, row in frame.iterrows():
        signal_date = _link_date_text(row["aligned_signal_date"], "aligned_signal_date")
        trade_date = _link_date_text(row["aligned_trade_date"], "aligned_trade_date")
        frame.at[index, "aligned_signal_date"] = signal_date
        frame.at[index, "aligned_trade_date"] = trade_date
        price_date_available = _price_date_available_bool(
            row["price_date_available"],
            index=index,
        )
        frame.at[index, "price_date_available"] = price_date_available

        if price_date_available:
            if signal_date is None:
                raise ValueError(
                    "aligned_signal_date must be present when "
                    "price_date_available is True."
                )
            if trade_date is None:
                raise ValueError(
                    "aligned_trade_date must be present when "
                    "price_date_available is True."
                )
            if signal_date != trade_date:
                raise ValueError(
                    "aligned_trade_date must equal aligned_signal_date when "
                    "price_date_available is True."
                )
            continue

        if signal_date is not None or trade_date is not None:
            raise ValueError(
                "price_date_available False rows must not contain aligned dates."
            )


def _link_date_text(value: object, column: str) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    date_text = _date_text(value, field_name=column, raise_invalid_numeric=True)
    if date_text is None:
        raise ValueError(f"{column} must be a valid date.")
    return date_text


def _price_date_available_bool(value: object, *, index: int) -> bool:
    if isinstance(value, bool):
        return value
    if type(value).__name__ == "bool_":
        return bool(value)
    if value in (0, 1):
        return bool(value)
    text = _optional_text(value)
    if text is not None:
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
    raise ValueError(f"price_date_available must be boolean for row {index}.")


def _is_numeric_date_value(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _numeric_date_text(
    value: object,
    *,
    field_name: str,
    raise_invalid: bool,
) -> str | None:
    number = float(value)  # type: ignore[arg-type]
    if math.isfinite(number) and number.is_integer():
        text = str(int(number))
        if re.fullmatch(r"\d{8}", text):
            try:
                return datetime.strptime(text, "%Y%m%d").date().isoformat()
            except ValueError:
                pass
    if raise_invalid:
        raise ValueError(f"{field_name} numeric values must use YYYYMMDD format.")
    return None


def _has_time_component(text: str) -> bool:
    return re.search(r"(?:T|\s)\d{1,2}:\d{2}", text) is not None
