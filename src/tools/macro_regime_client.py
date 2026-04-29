"""Structured macro regime events derived from cached benchmark OHLC data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import uuid

import pandas as pd
from loguru import logger

from src.backtest.data_loader import load_ohlc

BENCHMARKS = ("XBI", "IBB", "SPY", "TLT", "^VIX")
SECTOR_BENCHMARKS = ("XBI", "IBB")
UNDERPERFORMANCE_THRESHOLD = -0.08
VIX_RISK_OFF_LEVEL = 30.0


def build_macro_regime_events(
    ticker: str,
    benchmark_frames: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Build deterministic macro regime events from benchmark OHLC frames."""
    normalized_ticker = str(ticker or "").strip().upper()
    events: list[dict[str, Any]] = []
    spy_frame = _frame_for(benchmark_frames, "SPY")
    spy_return = _window_return(spy_frame)

    if spy_return is not None:
        for benchmark in SECTOR_BENCHMARKS:
            sector_frame = _frame_for(benchmark_frames, benchmark)
            sector_return = _window_return(sector_frame)
            event_date = _latest_date(sector_frame)
            if sector_return is None or event_date is None:
                continue

            relative_return = sector_return - spy_return
            if relative_return <= UNDERPERFORMANCE_THRESHOLD:
                events.append(
                    _event(
                        ticker=normalized_ticker,
                        event_type="sector_underperformance",
                        date=event_date,
                        basis=f"{benchmark}-vs-SPY",
                        benchmark=benchmark,
                        catalyst=(
                            f"{benchmark} underperformed SPY by "
                            f"{relative_return:.1%} over the macro window"
                        ),
                        metadata={
                            "benchmark": benchmark,
                            "relative_return": round(relative_return, 6),
                            "comparison_benchmark": "SPY",
                            "backtest_eligible": True,
                        },
                    )
                )

    vix_frame = _frame_for(benchmark_frames, "^VIX")
    vix_level = _latest_close(vix_frame)
    vix_date = _latest_date(vix_frame)
    if vix_level is not None and vix_date is not None and vix_level >= VIX_RISK_OFF_LEVEL:
        events.append(
            _event(
                ticker=normalized_ticker,
                event_type="macro_risk_off",
                date=vix_date,
                basis="^VIX",
                benchmark="^VIX",
                catalyst=f"VIX risk-off regime at {vix_level:.1f}",
                metadata={
                    "benchmark": "^VIX",
                    "level": round(vix_level, 3),
                    "backtest_eligible": True,
                },
            )
        )

    return events


def fetch_macro_regime_events(
    ticker: str,
    loader: Callable[[str], pd.DataFrame] = load_ohlc,
) -> list[dict[str, Any]]:
    """Load benchmark OHLC windows and build macro regime events."""
    frames: dict[str, pd.DataFrame] = {}
    for benchmark in BENCHMARKS:
        try:
            frame = loader(benchmark)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Macro regime OHLC load failed for {benchmark}: {exc}")
            continue

        if isinstance(frame, pd.DataFrame) and not frame.empty:
            frames[benchmark] = frame.tail(30).copy()

    return build_macro_regime_events(ticker, frames)


def _event(
    *,
    ticker: str,
    event_type: str,
    date: str,
    basis: str,
    benchmark: str,
    catalyst: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    event_metadata = {
        "category": "macro",
        "source_kind": "macro",
        "source_tier": "macro",
        **metadata,
    }
    return {
        "id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"macro_regime|{ticker}|{event_type}|{date}|{basis}",
            )
        ),
        "date": date,
        "type": event_type,
        "category": "macro",
        "priority": 2,
        "ticker": ticker,
        "disease_area": "",
        "catalyst": catalyst,
        "sentiment": "negative",
        "price_impact": None,
        "source": "macro_regime",
        "source_entity": benchmark,
        "source_ids": [basis],
        "confidence": "medium",
        "metadata": event_metadata,
    }


def _frame_for(
    frames: Mapping[str, pd.DataFrame],
    benchmark: str,
) -> pd.DataFrame | None:
    frame = frames.get(benchmark)
    return frame if isinstance(frame, pd.DataFrame) and not frame.empty else None


def _window_return(frame: pd.DataFrame | None) -> float | None:
    if frame is None or "close" not in frame.columns:
        return None

    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return None

    start = float(closes.iloc[0])
    end = float(closes.iloc[-1])
    if start == 0:
        return None
    return (end / start) - 1.0


def _latest_close(frame: pd.DataFrame | None) -> float | None:
    if frame is None or "close" not in frame.columns:
        return None

    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if closes.empty:
        return None
    return float(closes.iloc[-1])


def _latest_date(frame: pd.DataFrame | None) -> str | None:
    if frame is None or frame.empty:
        return None

    raw_dates = frame["date"] if "date" in frame.columns else frame.index
    dates = pd.Series(pd.to_datetime(raw_dates, errors="coerce")).dropna()

    if dates.empty:
        return None
    return dates.iloc[-1].strftime("%Y-%m-%d")
