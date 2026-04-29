"""Market data service with 24-hour cache freshness logic."""

from datetime import datetime, timedelta
from pathlib import Path

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


def _serialize_ohlc_frame(df: pd.DataFrame) -> list[dict]:
    """Serialize OHLC rows for chart compatibility."""
    if df.empty:
        return []
    serialized = df.copy()
    serialized["date"] = pd.to_datetime(serialized["date"]).dt.strftime("%Y-%m-%d")
    return serialized.to_dict(orient="records")


def get_ohlc_rows_with_status(ticker: str, max_age_hours: int = 24) -> dict:
    """Get OHLC rows plus source freshness status.

    Checks if cached Parquet is fresh (< max_age_hours old). If fresh, loads
    from cache. If stale or missing, refreshes from yfinance. When refresh
    fails but local cache can still be loaded, returns those cached rows with
    ``status='stale'`` so the UI can show usable but dated data.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        max_age_hours: Maximum cache age in hours before refresh (default 24)

    Returns:
        Dict with rows, status, and optional message.
    """
    cache_path = DATA_DIR / f"{ticker}.parquet"
    is_stale = _is_cache_stale(cache_path, max_age_hours)
    had_cache = cache_path.exists()

    try:
        df = refresh_ohlc(ticker) if is_stale else load_ohlc(ticker)
    except Exception as exc:
        if not is_stale or not had_cache:
            raise
        return _stale_payload(ticker, str(exc))

    rows = _serialize_ohlc_frame(df)
    if is_stale and had_cache and not rows:
        return _stale_payload(ticker, "refresh returned no rows")
    return {
        "rows": rows,
        "status": "ready" if rows else "empty",
        "message": None,
    }


def _stale_payload(ticker: str, message: str) -> dict:
    return {
        "rows": _serialize_ohlc_frame(load_ohlc(ticker)),
        "status": "stale",
        "message": message,
    }


def get_ohlc_rows(ticker: str, max_age_hours: int = 24) -> list[dict]:
    """Get OHLC rows with the historical list-only return contract."""
    payload = get_ohlc_rows_with_status(ticker, max_age_hours)
    return list(payload.get("rows") or [])
