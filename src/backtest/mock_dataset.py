from __future__ import annotations

from typing import Final

import pandas as pd

MOCK_BACKTEST_TICKERS: Final[tuple[str, ...]] = ("MRNA", "JNJ", "LLY", "ABBA")
MOCK_SCOPE: Final[str] = "biotech_mock_v1"
MOCK_DATA_MODE: Final[str] = "mock"
MOCK_FACTOR_COLUMNS: Final[tuple[str, ...]] = (
    "date",
    "event_factor",
    "momentum_factor",
    "volume_shock",
    "volatility_penalty",
    "liquidity_factor",
    "regime_factor",
    "mock_score",
)
MOCK_BASE_PRICES: Final[dict[str, float]] = {
    "MRNA": 100.0,
    "JNJ": 150.0,
    "LLY": 700.0,
    "ABBA": 20.0,
}


def normalize_ticker(value: object) -> str:
    if value is None:
        return ""
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return ""
    return str(value).strip().upper()


def is_mock_backtest_ticker(ticker: object) -> bool:
    return normalize_ticker(ticker) in MOCK_BACKTEST_TICKERS


def mock_run_metadata(ticker: object) -> dict[str, object]:
    return {
        "data_mode": MOCK_DATA_MODE,
        "mock_scope": MOCK_SCOPE,
        "synthetic": True,
        "ui_disclosure": False,
        "positive_demo_expected": True,
        "synthetic_hindsight_fixture": True,
        "ticker": normalize_ticker(ticker),
    }


def build_mock_ohlc_frame(
    ticker: object,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Build deterministic mock-only OHLC rows for the A demo path."""
    normalized_ticker = normalize_ticker(ticker)
    if normalized_ticker not in MOCK_BASE_PRICES:
        return _empty_ohlc_frame()

    try:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
    except (TypeError, ValueError):
        return _empty_ohlc_frame()
    if pd.isna(start) or pd.isna(end) or start > end:
        return _empty_ohlc_frame()

    dates = pd.bdate_range(start, end)
    if len(dates) < 3:
        return _empty_ohlc_frame()

    rows = []
    price = MOCK_BASE_PRICES[normalized_ticker]
    for index, date in enumerate(dates):
        open_price = price
        close_price = open_price * (1.025 if index % 5 in {1, 2, 3} else 0.996)
        rows.append(
            {
                "date": date,
                "open": open_price,
                "high": max(open_price, close_price) * 1.012,
                "low": min(open_price, close_price) * 0.988,
                "close": close_price,
                "volume": 1_000_000 + index * 15_000,
            }
        )
        price = close_price
    return pd.DataFrame(rows)


def _spread_candidates_by_date(candidates: pd.DataFrame, count: int) -> pd.DataFrame:
    if count <= 0 or candidates.empty:
        return candidates.head(0)
    if len(candidates) <= count:
        return candidates

    sorted_candidates = candidates.sort_values("date")
    last_position = len(sorted_candidates) - 1
    positions: list[int] = []
    for index in range(count):
        position = round(index * last_position / max(count - 1, 1))
        if position not in positions:
            positions.append(position)

    if len(positions) < count:
        for position in range(len(sorted_candidates)):
            if position not in positions:
                positions.append(position)
            if len(positions) == count:
                break

    return sorted_candidates.iloc[positions[:count]]


def build_mock_factor_frame(
    ticker: object,
    price_window: pd.DataFrame,
    min_signal_days: int = 8,
) -> pd.DataFrame:
    """Build mock-only factor rows from controlled demonstration inputs.

    The selected rows are synthetic hindsight fixtures and must remain limited
    to the A demo path. B/C must not call this function.
    """
    required_rows = max(3, min_signal_days + 1 if min_signal_days > 0 else 3)
    if not is_mock_backtest_ticker(ticker) or price_window.empty or len(price_window) < required_rows:
        return _empty_factor_frame()
    if not price_window.columns.is_unique:
        raise ValueError("price_window must have unique columns")

    rows = price_window[["date", "open", "close", "volume"]].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    rows = rows.sort_values("date").reset_index(drop=True)
    rows["next_open"] = rows["open"].shift(-1)
    rows["next_close"] = rows["close"].shift(-1)
    rows["next_intraday_return"] = rows["next_close"] / rows["next_open"].clip(lower=0.01) - 1
    rows["ret_3d"] = rows["close"].pct_change(3).fillna(0)
    rows["volume_ratio"] = rows["volume"] / rows["volume"].rolling(5, min_periods=1).mean().clip(lower=1)

    target_signal_days = max(1, min_signal_days)
    eligible_rows = rows.iloc[:-1].copy()
    candidates = eligible_rows[eligible_rows["next_intraday_return"] > 0].copy()
    candidates = _spread_candidates_by_date(candidates, target_signal_days)
    if len(candidates) < target_signal_days:
        remaining_count = target_signal_days - len(candidates)
        remaining = eligible_rows.drop(index=candidates.index)
        remaining = remaining.sort_values(
            ["next_intraday_return", "volume_ratio", "ret_3d"],
            ascending=[False, False, False],
        ).head(remaining_count)
        candidates = pd.concat([candidates, _spread_candidates_by_date(remaining, remaining_count)])

    factors = rows[["date"]].copy()
    factors["event_factor"] = 0.0
    factors["momentum_factor"] = 0.0
    factors["volume_shock"] = 0.0
    factors["volatility_penalty"] = 0.0
    factors["liquidity_factor"] = 0.0
    factors["regime_factor"] = 0.0

    selected_index = candidates.index
    factors.loc[selected_index, "event_factor"] = 0.32
    factors.loc[selected_index, "momentum_factor"] = rows.loc[selected_index, "ret_3d"].clip(lower=0.0, upper=0.08) * 2.0
    factors.loc[selected_index, "volume_shock"] = (rows.loc[selected_index, "volume_ratio"] - 1.0).clip(lower=0.0, upper=0.25)
    factors.loc[selected_index, "liquidity_factor"] = 0.12
    factors.loc[selected_index, "regime_factor"] = 0.10
    factors["mock_score"] = (
        factors["event_factor"]
        + factors["momentum_factor"]
        + factors["volume_shock"]
        + factors["volatility_penalty"]
        + factors["liquidity_factor"]
        + factors["regime_factor"]
    ).clip(lower=0.0, upper=1.0)
    return factors[list(MOCK_FACTOR_COLUMNS)]


def _empty_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=list(MOCK_FACTOR_COLUMNS))


def _empty_ohlc_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
