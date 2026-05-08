from __future__ import annotations

import pandas as pd
import pytest


def _tiingo_row(**overrides):
    row = {
        "date": "2026-05-01T00:00:00.000Z",
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 103.0,
        "volume": 12345,
        "adjOpen": 50.0,
        "adjHigh": 52.5,
        "adjLow": 49.5,
        "adjClose": 51.5,
        "adjVolume": 24690,
        "divCash": 0.25,
        "splitFactor": 2.0,
    }
    row.update(overrides)
    return row


def test_append_prices_daily_frame_allows_new_ticker_in_existing_snapshot(tmp_path):
    from src.backtest.price_snapshot import (
        append_prices_daily_frame,
        write_prices_daily_frame,
    )
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    existing = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    write_prices_daily_frame(existing, output_root=output_root)

    next_ticker = normalize_tiingo_eod_prices(
        [_tiingo_row(close=104.0, adjClose=52.0)],
        ticker="ABBA",
        data_snapshot_id="snap-tiingo",
    )

    append_prices_daily_frame(next_ticker, output_root=output_root)

    existing_path = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
        / "MRNA.parquet"
    )
    appended_path = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
        / "ABBA.parquet"
    )
    assert existing_path.exists()
    assert appended_path.exists()
    assert pd.read_parquet(appended_path).iloc[0]["ticker"] == "ABBA"


def test_append_prices_daily_frame_rejects_existing_ticker_year_partition(tmp_path):
    from src.backtest.price_snapshot import (
        append_prices_daily_frame,
        write_prices_daily_frame,
    )
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    frame = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    write_prices_daily_frame(frame, output_root=output_root)

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        append_prices_daily_frame(frame, output_root=output_root)


def test_append_prices_daily_frame_validates_required_columns_and_partition_keys(tmp_path):
    from src.backtest.price_snapshot import append_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    frame = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )

    missing_column = frame.drop(columns=["adj_close"])
    with pytest.raises(ValueError, match="adj_close"):
        append_prices_daily_frame(missing_column, output_root=output_root)

    invalid_partition = frame.copy()
    invalid_partition.loc[0, "ticker"] = "../BAD"
    invalid_partition.loc[0, "source_symbol"] = "../BAD"
    with pytest.raises(ValueError, match="ticker contains unsupported path characters"):
        append_prices_daily_frame(invalid_partition, output_root=output_root)

    assert list(output_root.rglob("*.parquet")) == []
