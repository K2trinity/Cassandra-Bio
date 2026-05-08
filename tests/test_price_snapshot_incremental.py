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


def test_append_prices_daily_frame_rejects_batched_overlap_without_combined_file(
    tmp_path,
):
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

    overlapping = normalize_tiingo_eod_prices(
        [_tiingo_row(close=104.0, adjClose=52.0)],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    new_ticker = normalize_tiingo_eod_prices(
        [_tiingo_row(close=105.0, adjClose=52.5)],
        ticker="ABBA",
        data_snapshot_id="snap-tiingo",
    )
    batched = pd.concat([overlapping, new_ticker], ignore_index=True)

    with pytest.raises(FileExistsError, match="overlap existing price rows"):
        append_prices_daily_frame(batched, output_root=output_root)

    partition = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
    )
    assert (partition / "MRNA.parquet").exists()
    assert not (partition / "ABBA_MRNA.parquet").exists()
    assert not (partition / "ABBA.parquet").exists()


def test_append_prices_daily_frame_rejects_overlap_in_combined_existing_file(
    tmp_path,
):
    from src.backtest.price_snapshot import (
        append_prices_daily_frame,
        write_prices_daily_frame,
    )
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    abba = normalize_tiingo_eod_prices(
        [_tiingo_row(close=104.0, adjClose=52.0)],
        ticker="ABBA",
        data_snapshot_id="snap-tiingo",
    )
    mrna = normalize_tiingo_eod_prices(
        [_tiingo_row(close=105.0, adjClose=52.5)],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    write_prices_daily_frame(pd.concat([abba, mrna]), output_root=output_root)

    partition = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
    )
    combined_path = partition / "ABBA_MRNA.parquet"
    assert combined_path.exists()

    with pytest.raises(FileExistsError, match="overlap existing price rows"):
        append_prices_daily_frame(mrna, output_root=output_root)

    assert combined_path.exists()
    assert not (partition / "MRNA.parquet").exists()


def test_append_prices_daily_frame_batched_new_tickers_writes_per_ticker_files(
    tmp_path,
):
    from src.backtest.price_snapshot import append_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    abba = normalize_tiingo_eod_prices(
        [_tiingo_row(close=104.0, adjClose=52.0)],
        ticker="ABBA",
        data_snapshot_id="snap-tiingo",
    )
    jnj = normalize_tiingo_eod_prices(
        [_tiingo_row(close=105.0, adjClose=52.5)],
        ticker="JNJ",
        data_snapshot_id="snap-tiingo",
    )
    batched = pd.concat([abba, jnj], ignore_index=True)

    append_prices_daily_frame(batched, output_root=output_root)

    partition = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
    )
    assert sorted(path.name for path in partition.glob("*.parquet")) == [
        "ABBA.parquet",
        "JNJ.parquet",
    ]
    assert pd.read_parquet(partition / "ABBA.parquet").iloc[0]["ticker"] == "ABBA"
    assert pd.read_parquet(partition / "JNJ.parquet").iloc[0]["ticker"] == "JNJ"


def test_append_prices_daily_frame_rejects_duplicate_logical_keys(tmp_path):
    from src.backtest.price_snapshot import append_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    frame = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    duplicated = pd.concat([frame, frame], ignore_index=True)

    with pytest.raises(ValueError, match="Duplicate price rows"):
        append_prices_daily_frame(duplicated, output_root=output_root)

    assert list(output_root.rglob("*.parquet")) == []


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
