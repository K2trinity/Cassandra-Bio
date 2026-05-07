from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.backtest.data_loader import DATA_DIR
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


def import_ohlc_cache_to_prices_daily(
    *,
    ohlc_dir: str | Path = DATA_DIR,
    output_root: str | Path | None = None,
    data_snapshot_id: str,
    source: str = "yfinance",
) -> dict[str, int]:
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
        _write_partition(normalized, root, source)
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
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"OHLC frame missing columns: {sorted(missing)}")

    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    source_id = source.upper().replace("-", "_")
    df["security_id"] = f"{source_id}:{ticker.upper()}"
    df["ticker"] = ticker.upper()
    df["adj_close"] = df["close"]
    df["vwap"] = pd.NA
    df["split_factor"] = 1.0
    df["dividend"] = 0.0
    df["delisting_return"] = pd.NA
    df["adjustment_mode"] = "vendor_or_raw_close"
    df["source"] = source
    df["source_symbol"] = ticker.upper()
    df["data_snapshot_id"] = data_snapshot_id
    df["ingested_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return df[PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)


def _write_partition(frame: pd.DataFrame, root: Path, source: str) -> None:
    for year, group in frame.groupby(pd.to_datetime(frame["date"]).dt.year):
        partition = root / f"source={source}" / f"year={int(year)}"
        partition.mkdir(parents=True, exist_ok=True)
        tickers = "_".join(sorted(group["ticker"].unique()))
        path = partition / f"{tickers}.parquet"
        group.to_parquet(path, index=False)
