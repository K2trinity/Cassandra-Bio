# src/backtest/data_loader.py
"""OHLC data fetcher: yfinance → Parquet storage."""

from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ohlc"


def fetch_ohlc(ticker: str, period: str = "10y") -> pd.DataFrame:
    """Download OHLC from yfinance and cache as Parquet."""
    path = DATA_DIR / f"{ticker}.parquet"
    if path.exists():
        return pd.read_parquet(path)

    df = _download_ohlc(ticker, period)
    if not df.empty:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    return df


def _download_ohlc(ticker: str, period: str = "10y") -> pd.DataFrame:
    """Download and normalize OHLC rows without touching the local cache."""
    import yfinance as yf

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(ticker, period=period, interval="1d", progress=False)
    if raw.empty:
        return pd.DataFrame()

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "open", "high", "low", "close", "volume"]].dropna()
    return df


def load_ohlc(ticker: str) -> pd.DataFrame:
    """Load cached Parquet. Returns empty DataFrame if not cached."""
    path = DATA_DIR / f"{ticker}.parquet"
    if not path.exists():
        return fetch_ohlc(ticker)
    return pd.read_parquet(path)


def refresh_ohlc(ticker: str) -> pd.DataFrame:
    """Force re-download and overwrite cache."""
    df = _download_ohlc(ticker)
    if not df.empty:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / f"{ticker}.parquet"
        df.to_parquet(path, index=False)
    return df
