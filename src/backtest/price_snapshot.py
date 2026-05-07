from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.backtest.data_loader import DATA_DIR
from src.backtest.data_sources import YFINANCE_PROFILE
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
    "volume",
    "vwap",
    "split_factor",
    "dividend",
    "delisting_return",
    "adjustment_mode",
    "source",
    "source_symbol",
    "data_snapshot_id",
    "ingested_at",
]

REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
REQUIRED_NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]
FLOAT_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "adj_close",
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
    tickers = 0
    rows = 0

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
        _write_partition(
            normalized,
            root,
            source=source,
            data_snapshot_id=data_snapshot_id,
        )
        tickers += 1
        rows += len(normalized)

    return {"tickers": tickers, "rows": rows}


def normalize_ohlc_frame(
    frame: pd.DataFrame,
    *,
    ticker: str,
    data_snapshot_id: str,
    source: str,
) -> pd.DataFrame:
    source = _validate_source(source)
    data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"OHLC frame missing columns: {sorted(missing)}")

    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for column in REQUIRED_NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", *REQUIRED_NUMERIC_COLUMNS])
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    source_id = source.upper().replace("-", "_")
    df["security_id"] = f"{source_id}:{ticker.upper()}"
    df["ticker"] = ticker.upper()
    df["adj_close"] = df["close"]
    df["vwap"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["split_factor"] = 1.0
    df["dividend"] = 0.0
    df["delisting_return"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adjustment_mode"] = "vendor_or_raw_close"
    df["source"] = source
    df["source_symbol"] = ticker.upper()
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


def _write_partition(
    frame: pd.DataFrame,
    root: Path,
    *,
    source: str,
    data_snapshot_id: str,
) -> None:
    for year, group in frame.groupby(pd.to_datetime(frame["date"]).dt.year):
        partition = (
            root
            / f"data_snapshot_id={data_snapshot_id}"
            / f"source={source}"
            / f"year={int(year)}"
        )
        partition.mkdir(parents=True, exist_ok=True)
        tickers = "_".join(sorted(group["ticker"].unique()))
        path = partition / f"{tickers}.parquet"
        group.to_parquet(path, index=False)


def _validate_source(source: str) -> str:
    if source != YFINANCE_PROFILE.source_id:
        raise ValueError(
            f"Unsupported OHLC source {source!r}; expected {YFINANCE_PROFILE.source_id!r}."
        )
    return _safe_partition_token("source", source)


def _safe_partition_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string.")
    if not SAFE_PARTITION_TOKEN.fullmatch(value):
        raise ValueError(f"{name} contains unsupported path characters: {value!r}.")
    return value
