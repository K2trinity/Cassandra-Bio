# src/backtest/features_v2.py
"""Enhanced feature engineering V2: market sentiment + candlestick patterns.

Adapted from PokieTicker — accepts DataFrames instead of SQLite queries.
"""

import pandas as pd

from src.backtest.features import build_features, FEATURE_COLS


FEATURE_COLS_V2_MARKET = FEATURE_COLS + [
    "mkt_sentiment", "mkt_positive_ratio",
    "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum",
]

FEATURE_COLS_V2_CANDLE = FEATURE_COLS_V2_MARKET + [
    "candle_body_ratio", "candle_bullish", "candle_upper_shadow",
    "candle_lower_shadow", "candle_doji", "candle_hammer",
    "candle_engulfing", "candle_streak",
]


def build_market_sentiment(all_events_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sentiment across ALL tickers per trading date.

    Args:
        all_events_df: DataFrame with columns [date, ticker, sentiment].
    """
    if all_events_df.empty:
        return pd.DataFrame()

    df = all_events_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])

    agg = df.groupby("trade_date").agg(
        mkt_articles=("id", "count"),
        mkt_positive=("sentiment", lambda x: (x == "positive").sum()),
        mkt_negative=("sentiment", lambda x: (x == "negative").sum()),
        mkt_tickers_active=("ticker", "nunique"),
    ).reset_index()

    total = agg["mkt_articles"].clip(lower=1)
    agg["mkt_sentiment"] = (agg["mkt_positive"] - agg["mkt_negative"]) / total
    agg["mkt_positive_ratio"] = agg["mkt_positive"] / total
    agg["mkt_sentiment_3d"] = agg["mkt_sentiment"].rolling(3, min_periods=1).mean()
    agg["mkt_sentiment_5d"] = agg["mkt_sentiment"].rolling(5, min_periods=1).mean()
    agg["mkt_momentum"] = agg["mkt_sentiment_3d"] - agg["mkt_sentiment_5d"]
    return agg


def add_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Add candlestick pattern features from OHLC data.

    All features shifted by 1 to prevent look-ahead leakage.
    """
    o, h, low, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - low).clip(lower=1e-10)

    df["candle_body_ratio"] = body / rng
    df["candle_bullish"] = (c > o).astype(int)

    upper_shadow = h - pd.concat([o, c], axis=1).max(axis=1)
    df["candle_upper_shadow"] = upper_shadow / rng

    lower_shadow = pd.concat([o, c], axis=1).min(axis=1) - low
    df["candle_lower_shadow"] = lower_shadow / rng

    df["candle_doji"] = (df["candle_body_ratio"] < 0.1).astype(int)
    df["candle_hammer"] = (
        (df["candle_lower_shadow"] > 0.6) & (df["candle_body_ratio"] < 0.3)
    ).astype(int)

    prev_bullish = df["candle_bullish"].shift(1)
    prev_body = body.shift(1)
    df["candle_engulfing"] = (
        (body > prev_body) & (df["candle_bullish"] != prev_bullish)
    ).astype(int).shift(1)

    df["candle_streak"] = (
        df["candle_bullish"].rolling(3, min_periods=1).sum().shift(1)
    )

    for col in [
        "candle_body_ratio", "candle_bullish", "candle_upper_shadow",
        "candle_lower_shadow", "candle_doji", "candle_hammer",
    ]:
        df[col] = df[col].shift(1)

    return df


def build_features_v2(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    all_events_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build enhanced feature matrix with market + candle features.

    Args:
        ohlc_df: Single ticker OHLC data.
        events_df: Events for this ticker.
        all_events_df: Events across ALL tickers (for market sentiment).
    """
    df = build_features(ohlc_df, events_df)
    if df.empty:
        return df

    # Market-wide sentiment
    mkt = build_market_sentiment(all_events_df)
    if not mkt.empty:
        df = df.merge(mkt[["trade_date", "mkt_sentiment", "mkt_positive_ratio",
                           "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum"]],
                      on="trade_date", how="left")
    for col in ["mkt_sentiment", "mkt_positive_ratio",
                "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0)

    # Candlestick patterns
    df = add_candle_patterns(df)

    # Additional targets for big moves
    close = df["close"]
    ret_t1 = close.shift(-1) / close - 1
    df["target_big1_t1"] = (ret_t1.abs() > 0.01).astype(int)
    df["target_big2_t1"] = (ret_t1.abs() > 0.02).astype(int)
    df["target_up_big_t1"] = (ret_t1 > 0.01).astype(int)
    df["target_down_big_t1"] = (ret_t1 < -0.01).astype(int)

    return df


def get_feature_cols_v2_full(df: pd.DataFrame) -> list[str]:
    """Get all V2 feature columns including any text SVD components."""
    text_cols = [c for c in df.columns if c.startswith("text_svd_")]
    return FEATURE_COLS_V2_CANDLE + text_cols
