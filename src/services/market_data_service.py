"""Market data service with 24-hour cache freshness logic."""

from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
import pandas as pd

from src.backtest.data_loader import load_ohlc, refresh_ohlc, DATA_DIR


def _is_cache_stale(path: Path, max_age_hours: int) -> bool:
    """Check if cached Parquet file is older than max_age_hours."""
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

    If refresh fails but a stale local cache exists, return the stale rows with
    status metadata. If no usable cache exists, return an error payload so the
    workspace can render a source status instead of crashing the route.
    """
    cache_path = DATA_DIR / f"{ticker}.parquet"
    is_stale = _is_cache_stale(cache_path, max_age_hours)
    had_cache = cache_path.exists()

    try:
        df = refresh_ohlc(ticker) if is_stale else load_ohlc(ticker)
    except Exception as exc:  # noqa: BLE001
        if is_stale and had_cache:
            return _stale_payload(ticker, str(exc))
        logger.warning(f"Failed to fetch OHLC for {ticker}: {exc}")
        return {"rows": [], "status": "error", "message": str(exc)}

    try:
        rows = _serialize_ohlc_frame(df)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to serialize OHLC rows for {ticker}: {exc}")
        return {"rows": [], "status": "error", "message": str(exc)}

    if is_stale and had_cache and not rows:
        return _stale_payload(ticker, "refresh returned no rows")
    return {
        "rows": rows,
        "status": "ready" if rows else "empty",
        "message": None,
    }


def get_cached_ohlc_rows_with_status(ticker: str, max_age_hours: int = 24) -> dict:
    """Return cached OHLC rows without downloading or refreshing data."""
    cache_path = DATA_DIR / f"{ticker}.parquet"
    if not cache_path.exists():
        return {
            "rows": [],
            "status": "empty",
            "message": "no cached OHLC available",
        }

    try:
        df = pd.read_parquet(cache_path)
        rows = _serialize_ohlc_frame(df)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load cached OHLC for {ticker}: {exc}")
        return {
            "rows": [],
            "status": "error",
            "message": str(exc),
        }

    if not rows:
        return {
            "rows": [],
            "status": "empty",
            "message": "cached OHLC is empty",
            "last_updated": _cache_mtime_iso(cache_path),
        }

    is_stale = _is_cache_stale(cache_path, max_age_hours)
    return {
        "rows": rows,
        "status": "stale" if is_stale else "ready",
        "message": "cached OHLC is stale; refresh pending" if is_stale else None,
        "last_updated": _cache_mtime_iso(cache_path),
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


def _cache_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None
