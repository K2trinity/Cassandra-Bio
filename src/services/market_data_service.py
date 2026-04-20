"""Market data service with 24-hour cache freshness logic."""

from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

from src.backtest.data_loader import load_ohlc, refresh_ohlc, DATA_DIR


def _is_cache_stale(path: Path, max_age_hours: int) -> bool:
    """Check if cached Parquet file is older than max_age_hours.

    Args:
        path: Path to the Parquet file
        max_age_hours: Maximum age in hours before cache is considered stale

    Returns:
        True if file doesn't exist or is older than max_age_hours, False otherwise
    """
    if not path.exists():
        return True

    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    age = datetime.now() - mtime
    return age > timedelta(hours=max_age_hours)


def get_ohlc_rows(ticker: str, max_age_hours: int = 24) -> list[dict]:
    """Get OHLC data with 24-hour cache freshness logic.

    Checks if cached Parquet is fresh (< max_age_hours old). If fresh, loads
    from cache. If stale or missing, refreshes from yfinance. Serializes dates
    to YYYY-MM-DD format for chart compatibility.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        max_age_hours: Maximum cache age in hours before refresh (default 24)

    Returns:
        List of dicts with keys: date (YYYY-MM-DD), open, high, low, close, volume
        Returns empty list if data fetch fails or DataFrame is empty
    """
    cache_path = DATA_DIR / f"{ticker}.parquet"

    # Decide whether to load from cache or refresh
    if _is_cache_stale(cache_path, max_age_hours):
        df = refresh_ohlc(ticker)
    else:
        df = load_ohlc(ticker)

    # Handle empty DataFrame
    if df.empty:
        return []

    # Serialize date to YYYY-MM-DD and convert to list of dicts
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.to_dict(orient="records")
