# src/backtest/strategy.py
"""Strategy execution: position sizing and risk management."""

import pandas as pd
import numpy as np


def apply_strategy(
    ohlc_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    max_position_pct: float = 0.20,
    stop_loss_pct: float = -0.08,
    drawdown_limit_pct: float = -0.15,
    slippage_pct: float = 0.001,
    holding_period_days: int = 1,
) -> pd.DataFrame:
    """Simulate strategy execution with risk controls.

    Assumptions:
        - T+1 open price execution
        - Single position at a time (long or short)
        - Slippage applied on entry and exit

    Args:
        ohlc_df: OHLC data with 'date', 'open', 'close'.
        signals_df: Signals with 'date', 'signal', 'signal_strength'.
        max_position_pct: Max portfolio allocation per position.
        stop_loss_pct: Single-day stop loss threshold.
        drawdown_limit_pct: Portfolio drawdown threshold for 50% reduction.
        slippage_pct: Slippage per trade (applied to entry price).
        holding_period_days: Trading days to keep the latest non-zero signal active.

    Returns:
        DataFrame with columns [date, position, daily_return, equity, drawdown].
    """
    df = ohlc_df[["date", "open", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    signals = signals_df.copy()
    signals["date"] = pd.to_datetime(signals["date"])
    df = df.merge(signals, on="date", how="left")
    df["signal"] = df["signal"].fillna(0).astype(int)
    df["signal_strength"] = df["signal_strength"].fillna(0)

    n = len(df)
    position = np.zeros(n)
    daily_ret = np.zeros(n)
    equity = np.ones(n)
    peak_equity = 1.0
    drawdown = np.zeros(n)
    scale = 1.0
    holding_days = max(1, int(holding_period_days))

    current_position = 0.0
    days_remaining = 0
    entry_price = 0.0

    for i in range(1, n):
        just_opened = False
        if current_position == 0:
            prev_signal = int(df["signal"].iloc[i - 1])
            if prev_signal != 0:
                strength = min(max(float(df["signal_strength"].iloc[i - 1]), 0.0), 1.0)
                current_position = prev_signal * strength * max_position_pct * scale
                days_remaining = holding_days
                entry_price = df["open"].iloc[i] * (
                    1 + slippage_pct * np.sign(current_position)
                )
                just_opened = True

        size = current_position
        position[i] = size

        close_price = float(df["close"].iloc[i])
        if size != 0:
            if just_opened:
                basis_price = entry_price
            else:
                basis_price = float(df["close"].iloc[i - 1])

            exit_today = days_remaining <= 1
            marked_price = close_price
            if exit_today:
                marked_price = close_price * (1 - slippage_pct * np.sign(size))

            price_return = (marked_price / basis_price - 1) * np.sign(size)
            daily_ret[i] = abs(size) * price_return
        else:
            daily_ret[i] = 0

        if daily_ret[i] < stop_loss_pct * abs(size):
            daily_ret[i] = stop_loss_pct * abs(size)
            days_remaining = 1

        equity[i] = equity[i - 1] * (1 + daily_ret[i])
        peak_equity = max(peak_equity, equity[i])
        drawdown[i] = equity[i] / peak_equity - 1

        if size != 0:
            days_remaining -= 1
            if days_remaining <= 0:
                current_position = 0.0
                entry_price = 0.0

        if drawdown[i] < drawdown_limit_pct:
            scale = 0.5
        elif drawdown[i] > drawdown_limit_pct * 0.5:
            scale = 1.0

    df["position"] = position
    df["daily_return"] = daily_ret
    df["equity"] = equity
    df["drawdown"] = drawdown

    return df[["date", "position", "daily_return", "equity", "drawdown"]]
