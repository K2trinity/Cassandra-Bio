from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest


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
    assert files[0].parent == (
        output_root / "data_snapshot_id=snap-test" / "source=yfinance" / "year=2026"
    )
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
    ingested_at = prices.iloc[0]["ingested_at"]
    assert ingested_at.endswith("Z")
    parsed_ingested_at = datetime.fromisoformat(
        ingested_at.replace("Z", "+00:00")
    )
    assert parsed_ingested_at.utcoffset().total_seconds() == 0


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


def test_import_ohlc_cache_keeps_snapshots_separate_for_same_ticker_year(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
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

    import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-one",
        source="yfinance",
    )
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 23456,
            }
        ]
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)
    import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-two",
        source="yfinance",
    )

    files = sorted(output_root.rglob("*.parquet"))
    first_snapshot = (
        output_root
        / "data_snapshot_id=snap-one"
        / "source=yfinance"
        / "year=2026"
        / "MRNA.parquet"
    )
    second_snapshot = (
        output_root
        / "data_snapshot_id=snap-two"
        / "source=yfinance"
        / "year=2026"
        / "MRNA.parquet"
    )
    assert files == [first_snapshot, second_snapshot]
    assert pd.read_parquet(first_snapshot).iloc[0]["data_snapshot_id"] == "snap-one"
    assert pd.read_parquet(second_snapshot).iloc[0]["data_snapshot_id"] == "snap-two"


def test_import_ohlc_cache_rejects_same_snapshot_overwrite(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
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

    import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        import_ohlc_cache_to_prices_daily(
            ohlc_dir=ohlc_dir,
            output_root=output_root,
            data_snapshot_id="snap-test",
            source="yfinance",
        )


def test_import_ohlc_cache_drops_invalid_numeric_rows_and_writes_numeric_dtypes(
    tmp_path,
):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
    ohlc_dir.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": "100.5",
                "high": "103.25",
                "low": "99.75",
                "close": "102.0",
                "volume": "12345",
            },
            {
                "date": "2026-05-02",
                "open": "not-a-number",
                "high": "104.0",
                "low": "98.0",
                "close": "101.0",
                "volume": "bad-volume",
            },
        ]
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)

    result = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    assert result == {"tickers": 1, "rows": 1}
    prices = pd.read_parquet(next(output_root.rglob("*.parquet")))
    assert len(prices) == 1
    assert str(prices.iloc[0]["date"]) == "2026-05-01"
    for column in [
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
    ]:
        assert pd.api.types.is_numeric_dtype(prices[column]), column


def test_import_ohlc_cache_drops_non_finite_and_invalid_price_rows(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
    ohlc_dir.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-02",
                "open": float("inf"),
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-03",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": -1,
            },
            {
                "date": "2026-05-04",
                "open": 100.0,
                "high": 94.0,
                "low": 95.0,
                "close": 96.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-05",
                "open": 101.0,
                "high": 100.0,
                "low": 90.0,
                "close": 95.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-06",
                "open": 95.0,
                "high": 100.0,
                "low": 90.0,
                "close": 101.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-07",
                "open": 95.0,
                "high": 110.0,
                "low": 96.0,
                "close": 100.0,
                "volume": 12345,
            },
            {
                "date": "2026-05-08",
                "open": 100.0,
                "high": 110.0,
                "low": 101.0,
                "close": 100.0,
                "volume": 12345,
            },
        ]
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)

    result = import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    assert result == {"tickers": 1, "rows": 1}
    prices = pd.read_parquet(next(output_root.rglob("*.parquet")))
    assert len(prices) == 1
    assert str(prices.iloc[0]["date"]) == "2026-05-01"


def test_normalize_ohlc_frame_empty_result_has_stable_dtypes():
    from src.backtest.price_snapshot import normalize_ohlc_frame

    result = normalize_ohlc_frame(
        pd.DataFrame(
            [
                {
                    "date": "2026-05-01",
                    "open": "not-a-number",
                    "high": "103.0",
                    "low": "99.0",
                    "close": "102.0",
                    "volume": "12345",
                }
            ]
        ),
        ticker="MRNA",
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    assert result.empty
    for column in [
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
    ]:
        assert pd.api.types.is_numeric_dtype(result[column]), column


def test_import_ohlc_cache_rejects_duplicate_security_date_rows(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
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
            },
            {
                "date": "2026-05-01",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 23456,
            },
        ]
    ).to_parquet(ohlc_dir / "MRNA.parquet", index=False)

    with pytest.raises(ValueError, match="Duplicate price rows"):
        import_ohlc_cache_to_prices_daily(
            ohlc_dir=ohlc_dir,
            output_root=output_root,
            data_snapshot_id="snap-test",
            source="yfinance",
        )


def test_import_ohlc_cache_rejects_unsupported_source_before_writing(tmp_path):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
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

    with pytest.raises(ValueError, match="Unsupported OHLC source"):
        import_ohlc_cache_to_prices_daily(
            ohlc_dir=ohlc_dir,
            output_root=output_root,
            data_snapshot_id="snap-test",
            source="bad/source",
        )

    assert list(output_root.rglob("*.parquet")) == []
