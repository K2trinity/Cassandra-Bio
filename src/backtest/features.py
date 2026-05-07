# src/backtest/features.py
"""Feature engineering V1: one row per trading day per ticker.

Adapted from PokieTicker — accepts DataFrames instead of SQLite queries.
"""

import pandas as pd


FEATURE_COLS = [
    "n_articles", "n_relevant", "n_positive", "n_negative", "n_neutral",
    "sentiment_score", "relevance_ratio", "positive_ratio", "negative_ratio", "has_news",
    "sentiment_score_3d", "sentiment_score_5d", "sentiment_score_10d",
    "positive_ratio_3d", "positive_ratio_5d", "positive_ratio_10d",
    "negative_ratio_3d", "negative_ratio_5d", "negative_ratio_10d",
    "news_count_3d", "news_count_5d", "news_count_10d",
    "sentiment_momentum_3d",
    "ret_1d", "ret_3d", "ret_5d", "ret_10d",
    "volatility_5d", "volatility_10d",
    "volume_ratio_5d", "gap", "ma5_vs_ma20", "rsi_14", "day_of_week",
]


def build_news_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate event data per trade_date into news-like features.

    Args:
        events_df: DataFrame with columns [date, type, priority, sentiment].
                   Can be empty.

    Returns:
        DataFrame indexed by trade_date with news aggregate columns.
    """
    if events_df.empty:
        return pd.DataFrame()

    df = events_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])

    agg = df.groupby("trade_date").agg(
        n_articles=("id", "count"),
        n_positive=("sentiment", lambda x: (x == "positive").sum()),
        n_negative=("sentiment", lambda x: (x == "negative").sum()),
        n_neutral=("sentiment", lambda x: (x == "neutral").sum()),
    ).reset_index()

    agg["n_relevant"] = df.groupby("trade_date")["priority"].apply(
        lambda x: (x <= 2).sum()
    ).values

    total = agg["n_articles"].clip(lower=1)
    agg["sentiment_score"] = (agg["n_positive"] - agg["n_negative"]) / total
    agg["relevance_ratio"] = agg["n_relevant"] / total
    agg["positive_ratio"] = agg["n_positive"] / total
    agg["negative_ratio"] = agg["n_negative"] / total
    agg["has_news"] = 1
    return agg


def build_features(ohlc_df: pd.DataFrame, events_df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix: one row per trading day.

    Args:
        ohlc_df: DataFrame with columns [date, open, high, low, close, volume].
        events_df: DataFrame with columns [id, date, type, priority, sentiment].

    Returns:
        DataFrame with FEATURE_COLS + target columns.
    """
    if ohlc_df.empty or len(ohlc_df) < 30:
        return pd.DataFrame()

    df = ohlc_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    news = build_news_features(events_df)
    if not news.empty:
        df = df.merge(news, on="trade_date", how="left")

    news_cols = [
        "n_articles", "n_relevant", "n_positive", "n_negative",
        "n_neutral", "sentiment_score", "relevance_ratio",
        "positive_ratio", "negative_ratio", "has_news",
    ]
    for col in news_cols:
        if col not in df.columns:
            df[col] = 0
    df[news_cols] = df[news_cols].fillna(0)

    # Rolling news features
    for w in [3, 5, 10]:
        df[f"sentiment_score_{w}d"] = df["sentiment_score"].rolling(w, min_periods=1).mean()
        df[f"positive_ratio_{w}d"] = df["positive_ratio"].rolling(w, min_periods=1).mean()
        df[f"negative_ratio_{w}d"] = df["negative_ratio"].rolling(w, min_periods=1).mean()
        df[f"news_count_{w}d"] = df["n_articles"].rolling(w, min_periods=1).sum()
    df["sentiment_momentum_3d"] = df["sentiment_score_3d"] - df["sentiment_score_10d"]

    # Price / technical features (shifted by 1 to prevent leakage)
    close = df["close"]
    df["ret_1d"] = close.pct_change(1).shift(1)
    df["ret_3d"] = close.pct_change(3).shift(1)
    df["ret_5d"] = close.pct_change(5).shift(1)
    df["ret_10d"] = close.pct_change(10).shift(1)

    df["volatility_5d"] = close.pct_change().rolling(5).std().shift(1)
    df["volatility_10d"] = close.pct_change().rolling(10).std().shift(1)

    avg_vol_5 = df["volume"].rolling(5).mean().shift(1)
    df["volume_ratio_5d"] = df["volume"].shift(1) / avg_vol_5.clip(lower=1)

    df["gap"] = (df["open"] / close.shift(1) - 1).shift(1)

    ma5 = close.rolling(5).mean().shift(1)
    ma20 = close.rolling(20).mean().shift(1)
    df["ma5_vs_ma20"] = ma5 / ma20.clip(lower=0.01) - 1

    delta = close.diff().shift(1)
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.clip(lower=1e-10)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    df["day_of_week"] = df["trade_date"].dt.dayofweek

    # Targets
    df["target_t1"] = (close.shift(-1) > close).astype(int)
    df["target_t2"] = (close.shift(-2) > close).astype(int)
    df["target_t3"] = (close.shift(-3) > close).astype(int)
    df["target_t5"] = (close.shift(-5) > close).astype(int)

    df = df.dropna(subset=["ret_10d", "rsi_14"]).reset_index(drop=True)
    return df
