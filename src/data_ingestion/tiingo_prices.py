from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping, Any

import numpy as np
import pandas as pd

from src.backtest.price_snapshot import FLOAT_COLUMNS, PRICE_COLUMNS, _empty_price_frame

TIINGO_REQUIRED_FIELDS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjOpen",
    "adjHigh",
    "adjLow",
    "adjClose",
    "adjVolume",
    "divCash",
    "splitFactor",
}

TIINGO_NUMERIC_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjOpen",
    "adjHigh",
    "adjLow",
    "adjClose",
    "adjVolume",
    "divCash",
    "splitFactor",
]


def normalize_tiingo_eod_prices(
    rows: Iterable[Mapping[str, Any]],
    *,
    ticker: str,
    data_snapshot_id: str,
) -> pd.DataFrame:
    rows = list(rows)
    if not rows:
        return _empty_price_frame()

    for index, row in enumerate(rows):
        missing = TIINGO_REQUIRED_FIELDS - set(row)
        if missing:
            raise ValueError(
                f"Tiingo row {index} missing required fields: {sorted(missing)}"
            )

    source_symbol = ticker.upper()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.date
    for column in TIINGO_NUMERIC_FIELDS:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["date", *TIINGO_NUMERIC_FIELDS])
    finite_values = np.isfinite(df[TIINGO_NUMERIC_FIELDS]).all(axis=1)
    df = df[finite_values]
    if df.empty:
        return _empty_price_frame()

    raw_ohlc = ["open", "high", "low", "close"]
    adjusted_ohlc = ["adjOpen", "adjHigh", "adjLow", "adjClose"]
    valid_rows = (
        (df[raw_ohlc] > 0).all(axis=1)
        & (df[adjusted_ohlc] > 0).all(axis=1)
        & (df["volume"] >= 0)
        & (df["adjVolume"] >= 0)
        & (df["splitFactor"] > 0)
        & (df["high"] >= df["low"])
        & (df["high"] >= df["open"])
        & (df["high"] >= df["close"])
        & (df["low"] <= df["open"])
        & (df["low"] <= df["close"])
        & (df["adjHigh"] >= df["adjLow"])
        & (df["adjHigh"] >= df["adjOpen"])
        & (df["adjHigh"] >= df["adjClose"])
        & (df["adjLow"] <= df["adjOpen"])
        & (df["adjLow"] <= df["adjClose"])
    )
    df = df[valid_rows]
    if df.empty:
        return _empty_price_frame()

    df["security_id"] = f"TIINGO:{source_symbol}"
    df["ticker"] = source_symbol
    df["adj_open"] = df["adjOpen"]
    df["adj_high"] = df["adjHigh"]
    df["adj_low"] = df["adjLow"]
    df["adj_close"] = df["adjClose"]
    df["adj_volume"] = df["adjVolume"]
    df["vwap"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["split_factor"] = df["splitFactor"]
    df["dividend"] = df["divCash"]
    df["delisting_return"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adjustment_mode"] = "tiingo_adjusted"
    df["adjustment_quality"] = "adjusted"
    df["source"] = "tiingo"
    df["source_symbol"] = source_symbol
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
