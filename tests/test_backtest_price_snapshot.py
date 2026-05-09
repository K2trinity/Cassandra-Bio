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
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_volume",
        "volume",
        "vwap",
        "split_factor",
        "dividend",
        "delisting_return",
        "adjustment_mode",
        "adjustment_quality",
        "source",
        "source_symbol",
        "data_snapshot_id",
        "ingested_at",
    ]
    assert prices.iloc[0]["security_id"] == "YFINANCE:MRNA"
    assert prices.iloc[0]["source"] == "yfinance"
    assert prices.iloc[0]["data_snapshot_id"] == "snap-test"
    assert pd.isna(prices.iloc[0]["adj_close"])
    assert pd.isna(prices.iloc[0]["adj_open"])
    assert pd.isna(prices.iloc[0]["adj_high"])
    assert pd.isna(prices.iloc[0]["adj_low"])
    assert pd.isna(prices.iloc[0]["adj_volume"])
    assert prices.iloc[0]["adjustment_mode"] == "raw_ohlc_cache"
    assert prices.iloc[0]["adjustment_quality"] == "raw_only"
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


def test_import_ohlc_cache_preflights_existing_snapshot_before_writing(tmp_path):
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

    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 10.0,
                "high": 13.0,
                "low": 9.0,
                "close": 12.0,
                "volume": 23456,
            }
        ]
    ).to_parquet(ohlc_dir / "ABBA.parquet", index=False)

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        import_ohlc_cache_to_prices_daily(
            ohlc_dir=ohlc_dir,
            output_root=output_root,
            data_snapshot_id="snap-test",
            source="yfinance",
        )

    abba_path = (
        output_root
        / "data_snapshot_id=snap-test"
        / "source=yfinance"
        / "year=2026"
        / "ABBA.parquet"
    )
    assert not abba_path.exists()


def test_import_ohlc_cache_rejects_existing_snapshot_root_for_new_ticker_only(
    tmp_path,
):
    from src.backtest.price_snapshot import import_ohlc_cache_to_prices_daily

    ohlc_dir = tmp_path / "ohlc"
    output_root = tmp_path / "prices_daily"
    ohlc_dir.mkdir()
    mrna_path = ohlc_dir / "MRNA.parquet"
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
    ).to_parquet(mrna_path, index=False)

    import_ohlc_cache_to_prices_daily(
        ohlc_dir=ohlc_dir,
        output_root=output_root,
        data_snapshot_id="snap-test",
        source="yfinance",
    )

    mrna_path.unlink()
    pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 10.0,
                "high": 13.0,
                "low": 9.0,
                "close": 12.0,
                "volume": 23456,
            }
        ]
    ).to_parquet(ohlc_dir / "ABBA.parquet", index=False)

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        import_ohlc_cache_to_prices_daily(
            ohlc_dir=ohlc_dir,
            output_root=output_root,
            data_snapshot_id="snap-test",
            source="yfinance",
        )

    abba_path = (
        output_root
        / "data_snapshot_id=snap-test"
        / "source=yfinance"
        / "year=2026"
        / "ABBA.parquet"
    )
    assert not abba_path.exists()


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
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_volume",
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
            {
                "date": "2026-05-09",
                "open": -10.0,
                "high": 1.0,
                "low": -20.0,
                "close": -5.0,
                "volume": 100,
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
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_volume",
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


def test_load_prices_daily_ohlc_reads_adjusted_tiingo_snapshot(tmp_path):
    from src.backtest.price_snapshot import (
        append_prices_daily_frame,
        load_prices_daily_ohlc,
    )
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    frame = normalize_tiingo_eod_prices(
        [
            {
                "date": "2026-05-01T00:00:00.000Z",
                "open": 100.0,
                "high": 106.0,
                "low": 98.0,
                "close": 104.0,
                "volume": 1000,
                "adjOpen": 50.0,
                "adjHigh": 53.0,
                "adjLow": 49.0,
                "adjClose": 52.0,
                "adjVolume": 2000,
                "divCash": 0.0,
                "splitFactor": 2.0,
            },
            {
                "date": "2026-05-04T00:00:00.000Z",
                "open": 104.0,
                "high": 110.0,
                "low": 103.0,
                "close": 108.0,
                "volume": 1200,
                "adjOpen": 52.0,
                "adjHigh": 55.0,
                "adjLow": 51.5,
                "adjClose": 54.0,
                "adjVolume": 2400,
                "divCash": 0.0,
                "splitFactor": 2.0,
            },
        ],
        ticker="mrna",
        data_snapshot_id="snap-tiingo",
    )
    append_prices_daily_frame(frame, output_root=output_root)

    loaded = load_prices_daily_ohlc(
        "mrna",
        data_snapshot_id="snap-tiingo",
        output_root=output_root,
        source="tiingo",
    )

    assert loaded.to_dict("records") == [
        {
            "date": pd.Timestamp("2026-05-01"),
            "open": 50.0,
            "high": 53.0,
            "low": 49.0,
            "close": 52.0,
            "volume": 2000.0,
        },
        {
            "date": pd.Timestamp("2026-05-04"),
            "open": 52.0,
            "high": 55.0,
            "low": 51.5,
            "close": 54.0,
            "volume": 2400.0,
        },
    ]


def test_load_prices_daily_ohlc_returns_empty_frame_for_missing_snapshot(tmp_path):
    from src.backtest.price_snapshot import load_prices_daily_ohlc

    loaded = load_prices_daily_ohlc(
        "MRNA",
        data_snapshot_id="snap-missing",
        output_root=tmp_path / "prices_daily",
        source="tiingo",
    )

    assert loaded.empty
    assert list(loaded.columns) == ["date", "open", "high", "low", "close", "volume"]
