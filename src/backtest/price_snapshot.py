from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.data_loader import DATA_DIR
from src.backtest.data_sources import TIINGO_PROFILE, YFINANCE_PROFILE
from src.backtest.research_db import RESEARCH_DIR

PRICE_COLUMNS = [
    "security_id",
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_volume",
    "volume",
    "vwap",
    "split_factor",
    "dividend",
    "delisting_return",
    "adjustment_mode",
    "adjustment_quality",
    "source",
    "source_symbol",
    "data_snapshot_id",
    "ingested_at",
]

REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
OHLC_COLUMNS = ["open", "high", "low", "close"]
REQUIRED_NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]
FLOAT_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_volume",
    "volume",
    "vwap",
    "split_factor",
    "dividend",
    "delisting_return",
]
SAFE_PARTITION_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")


def import_ohlc_cache_to_prices_daily(
    *,
    ohlc_dir: str | Path = DATA_DIR,
    output_root: str | Path | None = None,
    data_snapshot_id: str,
    source: str = "yfinance",
) -> dict[str, int]:
    source = _validate_source(source)
    data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
    input_dir = Path(ohlc_dir)
    root = Path(output_root) if output_root is not None else RESEARCH_DIR / "prices_daily"
    snapshot_root = root / f"data_snapshot_id={data_snapshot_id}"
    tickers = 0
    rows = 0
    pending_writes = []

    for path in sorted(input_dir.glob("*.parquet")):
        ticker = path.stem.upper()
        raw = pd.read_parquet(path)
        if raw.empty:
            continue
        normalized = normalize_ohlc_frame(
            raw,
            ticker=ticker,
            data_snapshot_id=data_snapshot_id,
            source=source,
        )
        if normalized.empty:
            continue
        pending_writes.extend(
            _plan_partition_writes(
                normalized,
                root,
                source=source,
                data_snapshot_id=data_snapshot_id,
            )
        )
        tickers += 1
        rows += len(normalized)

    if pending_writes and snapshot_root.exists():
        raise FileExistsError(f"Price snapshot already exists: {snapshot_root}")
    _preflight_partition_writes(pending_writes)
    _write_planned_partitions(pending_writes)

    return {"tickers": tickers, "rows": rows}


def normalize_ohlc_frame(
    frame: pd.DataFrame,
    *,
    ticker: str,
    data_snapshot_id: str,
    source: str,
) -> pd.DataFrame:
    source = _validate_source(source)
    ticker = _safe_partition_token("ticker", ticker.upper())
    data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"OHLC frame missing columns: {sorted(missing)}")

    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for column in REQUIRED_NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", *REQUIRED_NUMERIC_COLUMNS])
    finite_values = np.isfinite(df[REQUIRED_NUMERIC_COLUMNS]).all(axis=1)
    df = df[finite_values]
    valid_price_rows = (
        (df[OHLC_COLUMNS] > 0).all(axis=1)
        & (df["volume"] >= 0)
        & (df["high"] >= df["low"])
        & (df["high"] >= df["open"])
        & (df["high"] >= df["close"])
        & (df["low"] <= df["open"])
        & (df["low"] <= df["close"])
    )
    df = df[valid_price_rows]
    if df.empty:
        return _empty_price_frame()

    source_id = source.upper().replace("-", "_")
    df["security_id"] = f"{source_id}:{ticker}"
    df["ticker"] = ticker
    df["adj_close"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_open"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_high"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_low"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_volume"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["vwap"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["split_factor"] = 1.0
    df["dividend"] = 0.0
    df["delisting_return"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adjustment_mode"] = "raw_ohlc_cache"
    df["adjustment_quality"] = "raw_only"
    df["source"] = source
    df["source_symbol"] = ticker
    df["data_snapshot_id"] = data_snapshot_id
    df["ingested_at"] = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    for column in FLOAT_COLUMNS:
        df[column] = df[column].astype("float64")

    duplicates = df.duplicated(subset=["security_id", "date"], keep=False)
    if duplicates.any():
        duplicate_keys = (
            df.loc[duplicates, ["security_id", "date"]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise ValueError(f"Duplicate price rows for security/date: {duplicate_keys}")

    return df[PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)


def write_prices_daily_frame(
    frame: pd.DataFrame,
    *,
    output_root: str | Path | None = None,
) -> None:
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Price frame missing columns: {missing}")
    _validate_price_frame_partition_keys(frame)
    _validate_price_frame_unique_logical_keys(frame)

    root = Path(output_root) if output_root is not None else RESEARCH_DIR / "prices_daily"
    pending_writes = []
    snapshot_roots = set()
    for (source, data_snapshot_id), group in frame.groupby(
        ["source", "data_snapshot_id"],
        sort=True,
    ):
        source = _validate_source(source)
        data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
        snapshot_roots.add(root / f"data_snapshot_id={data_snapshot_id}")
        pending_writes.extend(
            _plan_partition_writes(
                group[PRICE_COLUMNS],
                root,
                source=source,
                data_snapshot_id=data_snapshot_id,
            )
        )

    for snapshot_root in snapshot_roots:
        if snapshot_root.exists():
            raise FileExistsError(f"Price snapshot already exists: {snapshot_root}")
    _preflight_partition_writes(pending_writes)
    _write_planned_partitions(pending_writes)


def append_prices_daily_frame(
    frame: pd.DataFrame,
    *,
    output_root: str | Path | None = None,
) -> None:
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Price frame missing columns: {missing}")
    _validate_price_frame_partition_keys(frame)
    _validate_price_frame_unique_logical_keys(frame)

    root = (
        Path(output_root) if output_root is not None else RESEARCH_DIR / "prices_daily"
    )
    pending_writes = []
    for (source, data_snapshot_id), group in frame.groupby(
        ["source", "data_snapshot_id"],
        sort=True,
    ):
        source = _validate_source(source)
        data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
        _ensure_no_existing_price_key_overlap(
            group[PRICE_COLUMNS],
            root,
            source=source,
            data_snapshot_id=data_snapshot_id,
        )
        pending_writes.extend(
            _plan_append_partition_writes(
                group[PRICE_COLUMNS],
                root,
                source=source,
                data_snapshot_id=data_snapshot_id,
            )
        )

    _preflight_partition_writes(pending_writes)
    _write_planned_partitions(pending_writes)


def _write_partition(
    frame: pd.DataFrame,
    root: Path,
    *,
    source: str,
    data_snapshot_id: str,
) -> None:
    pending_writes = _plan_partition_writes(
        frame,
        root,
        source=source,
        data_snapshot_id=data_snapshot_id,
    )
    _preflight_partition_writes(pending_writes)
    _write_planned_partitions(pending_writes)


def _plan_partition_writes(
    frame: pd.DataFrame,
    root: Path,
    *,
    source: str,
    data_snapshot_id: str,
) -> list[tuple[pd.DataFrame, Path, Path]]:
    pending_writes = []
    for year, group in frame.groupby(pd.to_datetime(frame["date"]).dt.year):
        partition = (
            root
            / f"data_snapshot_id={data_snapshot_id}"
            / f"source={source}"
            / f"year={int(year)}"
        )
        tickers = "_".join(
            sorted(
                _safe_partition_token("ticker", ticker)
                for ticker in group["ticker"].unique()
            )
        )
        path = partition / f"{tickers}.parquet"
        pending_writes.append((group, partition, path))
    return pending_writes


def _plan_append_partition_writes(
    frame: pd.DataFrame,
    root: Path,
    *,
    source: str,
    data_snapshot_id: str,
) -> list[tuple[pd.DataFrame, Path, Path]]:
    pending_writes = []
    years = pd.to_datetime(frame["date"]).dt.year
    for (year, ticker), group in frame.groupby([years, "ticker"], sort=True):
        safe_ticker = _safe_partition_token("ticker", ticker)
        partition = (
            root
            / f"data_snapshot_id={data_snapshot_id}"
            / f"source={source}"
            / f"year={int(year)}"
        )
        pending_writes.append((group, partition, partition / f"{safe_ticker}.parquet"))
    return pending_writes


def _validate_price_frame_partition_keys(frame: pd.DataFrame) -> None:
    for row_number, row in frame.reset_index(drop=True).iterrows():
        source = _require_non_null_partition_value(row["source"], "source", row_number)
        data_snapshot_id = _require_non_null_partition_value(
            row["data_snapshot_id"],
            "data_snapshot_id",
            row_number,
        )
        ticker = _require_non_null_partition_value(row["ticker"], "ticker", row_number)
        source_symbol = _require_non_null_partition_value(
            row["source_symbol"],
            "source_symbol",
            row_number,
        )

        _validate_source(source)
        _safe_partition_token("data_snapshot_id", data_snapshot_id)
        _safe_partition_token("ticker", ticker)
        _safe_partition_token("source_symbol", source_symbol)


def _validate_price_frame_unique_logical_keys(frame: pd.DataFrame) -> None:
    key_frame = _price_key_frame(frame)
    duplicates = key_frame.duplicated(keep=False)
    if duplicates.any():
        duplicate_keys = key_frame.loc[duplicates].drop_duplicates().to_dict("records")
        raise ValueError(f"Duplicate price rows for logical keys: {duplicate_keys}")


def _ensure_no_existing_price_key_overlap(
    frame: pd.DataFrame,
    root: Path,
    *,
    source: str,
    data_snapshot_id: str,
) -> None:
    incoming_keys = _price_key_set(frame)
    years = sorted(pd.to_datetime(frame["date"]).dt.year.dropna().unique())
    for year in years:
        partition = (
            root
            / f"data_snapshot_id={data_snapshot_id}"
            / f"source={source}"
            / f"year={int(year)}"
        )
        if not partition.exists():
            continue
        for path in sorted(partition.glob("*.parquet")):
            existing = pd.read_parquet(path)
            missing = [
                column for column in PRICE_COLUMNS if column not in existing.columns
            ]
            if missing:
                raise ValueError(
                    f"Existing price partition {path} missing columns: {missing}"
                )
            overlapping = incoming_keys & _price_key_set(existing[PRICE_COLUMNS])
            if overlapping:
                sample = sorted(overlapping)[:5]
                raise FileExistsError(
                    "Price snapshot already exists: incoming price rows "
                    "overlap existing price rows "
                    f"in {path}: {sample}"
                )


def _price_key_set(frame: pd.DataFrame) -> set[tuple[str, str, str, object]]:
    return set(_price_key_frame(frame).itertuples(index=False, name=None))


def _price_key_frame(frame: pd.DataFrame) -> pd.DataFrame:
    keys = frame[["source", "data_snapshot_id", "security_id", "date"]].copy()
    keys["date"] = pd.to_datetime(keys["date"], errors="coerce").dt.date
    return keys


def _require_non_null_partition_value(value: object, name: str, row_number: int) -> str:
    if pd.isna(value):
        raise ValueError(f"{name} must be a non-empty string at row {row_number}.")
    return _safe_partition_token(name, value)


def _preflight_partition_writes(
    pending_writes: list[tuple[pd.DataFrame, Path, Path]],
) -> None:
    for _, _, path in pending_writes:
        if path.exists():
            raise FileExistsError(f"Price snapshot already exists: {path}")


def _write_planned_partitions(
    pending_writes: list[tuple[pd.DataFrame, Path, Path]],
) -> None:
    for group, partition, path in pending_writes:
        partition.mkdir(parents=True, exist_ok=True)
        group.to_parquet(path, index=False)


def _validate_source(source: str) -> str:
    supported_sources = {YFINANCE_PROFILE.source_id, TIINGO_PROFILE.source_id}
    if source not in supported_sources:
        raise ValueError(
            f"Unsupported OHLC source {source!r}; "
            f"expected one of {sorted(supported_sources)!r}."
        )
    return _safe_partition_token("source", source)


def _safe_partition_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string.")
    if not SAFE_PARTITION_TOKEN.fullmatch(value):
        raise ValueError(f"{name} contains unsupported path characters: {value!r}.")
    return value


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.Series(dtype="float64" if column in FLOAT_COLUMNS else "object")
            for column in PRICE_COLUMNS
        }
    )
