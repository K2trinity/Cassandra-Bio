from __future__ import annotations

import pandas as pd


def test_import_ohlc_cache_writes_prices_daily_schema(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "research" / "prices_daily"
    ohlc_dir.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 12345,
            }
        ]
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)

    result = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    assert result == {"tickers": 1, "rows": 1}
    files = list(output_root.rglob("*.parquet"))
    assert len(files) == 1
    prices = pd.read_parquet(files[0])
    assert list(prices.columns) == [
        "security_id",
        "ticker",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "vwap",
        "split_factor",
        "dividend",
        "delisting_return",
        "adjustment_mode",
        "source",
        "source_symbol",
        "data_snapshot_id",
        "ingested_at",
    ]
    assert prices.iloc[0]["security_id"] == "YFINANCE:MRNA"
    assert prices.iloc[0]["source"] == "yfinance"
    assert prices.iloc[0]["data_snapshot_id"] == "snap-test"


def test_import_ohlc_cache_skips_empty_files(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
    ohlc_dir.mkdir()
    pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume"]
    ).to_parquet(ohlc_dir / "EMPTY.parquet", index=False)

    result = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    assert result == {"tickers": 0, "rows": 0}
    assert list(output_root.rglob("*.parquet")) == []
