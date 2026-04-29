"""Backtest attribution diagnostics for phase2 Kline events."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.kline.event_filter import decode_metadata


def summarize_events(events: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Return count summaries for eligible events used by a backtest."""
    if events.empty:
        return {"by_source": [], "by_category": [], "by_type": []}

    rows = events.copy()
    rows["category"] = rows.apply(_category_from_row, axis=1)

    return {
        "by_source": _count_rows(rows, "source"),
        "by_category": _count_rows(rows, "category"),
        "by_type": _count_rows(rows, "type"),
    }


def summarize_signals(signals: pd.DataFrame) -> dict[str, Any]:
    """Return compact signal activity diagnostics."""
    if signals.empty or "signal" not in signals.columns:
        return {
            "active_signal_days": 0,
            "long_signal_days": 0,
            "short_signal_days": 0,
            "mean_signal_strength": 0.0,
        }

    active = signals[signals["signal"] != 0]
    mean_strength = 0.0
    if not active.empty and "signal_strength" in active.columns:
        mean_strength = _safe_float(active["signal_strength"].mean()) or 0.0

    return {
        "active_signal_days": int(len(active)),
        "long_signal_days": int((signals["signal"] > 0).sum()),
        "short_signal_days": int((signals["signal"] < 0).sum()),
        "mean_signal_strength": round(mean_strength, 6),
    }


def compute_baseline(
    price_window: pd.DataFrame, results: pd.DataFrame
) -> dict[str, float | None]:
    """Return buy-and-hold and strategy baseline returns for the same window."""
    empty_result = {
        "buy_hold_return": None,
        "strategy_return": None,
        "excess_return": None,
    }
    if price_window.empty or len(price_window) < 2 or results.empty:
        return empty_result
    if (
        not {"open", "close"}.issubset(price_window.columns)
        or "equity" not in results.columns
    ):
        return empty_result

    first_open = _safe_float(price_window.iloc[0]["open"])
    last_close = _safe_float(price_window.iloc[-1]["close"])
    first_equity = _safe_float(results.iloc[0]["equity"])
    last_equity = _safe_float(results.iloc[-1]["equity"])

    buy_hold = None
    if first_open not in (None, 0.0) and last_close is not None:
        buy_hold = last_close / first_open - 1

    strategy = None
    if first_equity not in (None, 0.0) and last_equity is not None:
        strategy = last_equity / first_equity - 1

    excess = (
        strategy - buy_hold if strategy is not None and buy_hold is not None else None
    )
    return {
        "buy_hold_return": _round_optional(buy_hold),
        "strategy_return": _round_optional(strategy),
        "excess_return": _round_optional(excess),
    }


def _count_rows(rows: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if column not in rows.columns:
        return []
    grouped = rows.copy()
    grouped[column] = grouped[column].map(_label_value)
    counts = grouped.groupby(column).size().reset_index(name="count")
    return [
        {column: str(item[column]), "count": int(item["count"])}
        for item in counts.to_dict("records")
    ]


def _category_from_row(row: pd.Series) -> str:
    metadata = decode_metadata(row.get("metadata"))
    category = _label_value(row.get("category")) if "category" in row else "unknown"
    if category != "unknown":
        return category
    metadata_category = _label_value(metadata.get("category"))
    if metadata_category != "unknown":
        return metadata_category
    source_tier = metadata.get("source_tier")
    if source_tier == "market_news":
        return "news"
    if source_tier == "macro":
        return "macro"
    if source_tier == "official":
        return "clinical"
    return "clinical"


def _label_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float) and math.isnan(value):
        return "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _round_optional(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
