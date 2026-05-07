# src/backtest/metrics.py
"""Performance metrics for backtest evaluation."""

import pandas as pd
import numpy as np
from typing import Dict, Any


def compute_metrics(results_df: pd.DataFrame, benchmark_df: pd.DataFrame = None) -> Dict[str, Any]:
    """Compute three-layer performance metrics.

    Args:
        results_df: Strategy results with [date, daily_return, equity, drawdown].
        benchmark_df: Optional benchmark OHLC (e.g., XBI) with [date, close].

    Returns:
        Dict with layer1 (event), layer2 (signal), layer3 (strategy) metrics.
    """
    rets = results_df["daily_return"].dropna()
    equity = results_df["equity"]
    trading_days = 252

    total_days = len(rets)
    if total_days < 2:
        return {"error": "insufficient data"}

    ann_return = (equity.iloc[-1] / equity.iloc[0]) ** (trading_days / total_days) - 1
    ann_vol = rets.std() * np.sqrt(trading_days)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0
    max_dd = results_df["drawdown"].min()

    winning_days = (rets > 0).sum()
    losing_days = (rets < 0).sum()
    active_days = winning_days + losing_days
    win_rate = winning_days / active_days if active_days > 0 else 0

    gross_profit = rets[rets > 0].sum()
    gross_loss = abs(rets[rets < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    positions = results_df["position"]
    turnover = positions.diff().abs().sum() / total_days * trading_days

    metrics: Dict[str, Any] = {
        "layer3_strategy": {
            "annualized_return": round(ann_return, 4),
            "annualized_volatility": round(ann_vol, 4),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "annual_turnover": round(turnover, 2),
            "total_trading_days": total_days,
        },
    }

    if benchmark_df is not None and not benchmark_df.empty:
        bench = benchmark_df.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        merged = results_df.merge(bench[["date", "close"]], on="date", how="inner", suffixes=("", "_bench"))
        if len(merged) > 1:
            bench_ann = (merged["close"].iloc[-1] / merged["close"].iloc[0]) ** (trading_days / len(merged)) - 1
            excess = ann_return - bench_ann
            metrics["layer3_strategy"]["benchmark_return"] = round(bench_ann, 4)
            metrics["layer3_strategy"]["excess_return"] = round(excess, 4)

    return metrics


def compute_event_car(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    window_before: int = 5,
    window_after: int = 10,
) -> pd.DataFrame:
    """Compute Cumulative Abnormal Return (CAR) around events.

    Layer 1 metric: event predictability.

    Returns:
        DataFrame with [event_id, event_type, car, t_stat].
    """
    if events_df.empty or ohlc_df.empty:
        return pd.DataFrame()

    ohlc = ohlc_df.copy()
    ohlc["date"] = pd.to_datetime(ohlc["date"])
    ohlc = ohlc.sort_values("date").reset_index(drop=True)
    ohlc["ret"] = ohlc["close"].pct_change()

    results = []
    for _, evt in events_df.iterrows():
        evt_date = pd.to_datetime(evt["date"])
        idx = ohlc.index[ohlc["date"] == evt_date]
        if len(idx) == 0:
            continue
        i = idx[0]

        start = max(0, i - window_before)
        end = min(len(ohlc) - 1, i + window_after)

        window_rets = ohlc["ret"].iloc[start:end + 1].dropna()
        if len(window_rets) < 3:
            continue

        car = window_rets.sum()
        std = window_rets.std()
        t_stat = car / (std * np.sqrt(len(window_rets))) if std > 0 else 0

        results.append({
            "event_id": evt.get("id", ""),
            "event_type": evt.get("type", ""),
            "date": evt["date"],
            "car": round(car, 4),
            "t_stat": round(t_stat, 3),
        })

    return pd.DataFrame(results)
