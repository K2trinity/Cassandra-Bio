from __future__ import annotations

from datetime import date

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


def test_normalize_tiingo_eod_prices_outputs_adjusted_prices_daily_schema():
    from src.backtest.price_snapshot import PRICE_COLUMNS
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    result = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="mrna",
        data_snapshot_id="snap-tiingo",
    )

    assert list(result.columns) == PRICE_COLUMNS
    assert len(result) == 1
    row = result.iloc[0]
    assert row["security_id"] == "TIINGO:MRNA"
    assert row["ticker"] == "MRNA"
    assert row["date"] == date(2026, 5, 1)
    assert row["source"] == "tiingo"
    assert row["source_symbol"] == "MRNA"
    assert row["data_snapshot_id"] == "snap-tiingo"
    assert row["open"] == 100.0
    assert row["high"] == 105.0
    assert row["low"] == 99.0
    assert row["close"] == 103.0
    assert row["volume"] == 12345.0
    assert row["adj_open"] == 50.0
    assert row["adj_high"] == 52.5
    assert row["adj_low"] == 49.5
    assert row["adj_close"] == 51.5
    assert row["adj_volume"] == 24690.0
    assert row["split_factor"] == 2.0
    assert row["dividend"] == 0.25
    assert row["adjustment_mode"] == "tiingo_adjusted"
    assert row["adjustment_quality"] == "adjusted"
    assert row["ingested_at"].endswith("Z")


def test_normalize_tiingo_eod_prices_rejects_row_missing_adj_close():
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    row = _tiingo_row()
    del row["adjClose"]

    with pytest.raises(ValueError, match="adjClose"):
        normalize_tiingo_eod_prices(
            [row],
            ticker="MRNA",
            data_snapshot_id="snap-tiingo",
        )


def test_normalize_tiingo_eod_prices_rejects_duplicate_security_date_rows():
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    with pytest.raises(ValueError, match="Duplicate price rows"):
        normalize_tiingo_eod_prices(
            [_tiingo_row(), _tiingo_row(close=104.0, adjClose=52.0)],
            ticker="MRNA",
            data_snapshot_id="snap-tiingo",
        )


def test_normalize_tiingo_eod_prices_empty_input_returns_price_columns():
    from src.backtest.price_snapshot import FLOAT_COLUMNS, PRICE_COLUMNS
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    result = normalize_tiingo_eod_prices(
        [],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )

    assert result.empty
    assert list(result.columns) == PRICE_COLUMNS
    for column in FLOAT_COLUMNS:
        assert pd.api.types.is_numeric_dtype(result[column]), column


def test_write_prices_daily_frame_writes_tiingo_partitions_and_preflights_overwrite(
    tmp_path,
):
    from src.backtest.price_snapshot import write_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    frame = normalize_tiingo_eod_prices(
        [
            _tiingo_row(date="2026-05-01T00:00:00.000Z"),
            _tiingo_row(date="2027-01-02T00:00:00.000Z"),
        ],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )

    write_prices_daily_frame(frame, output_root=output_root)

    first_path = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
        / "MRNA.parquet"
    )
    second_path = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2027"
        / "MRNA.parquet"
    )
    assert first_path.exists()
    assert second_path.exists()
    assert pd.read_parquet(first_path).iloc[0]["adjustment_quality"] == "adjusted"

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        write_prices_daily_frame(frame, output_root=output_root)


def test_write_prices_daily_frame_rejects_existing_snapshot_root_before_writing(
    tmp_path,
):
    from src.backtest.price_snapshot import write_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    existing = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    write_prices_daily_frame(existing, output_root=output_root)

    next_ticker = normalize_tiingo_eod_prices(
        [_tiingo_row()],
        ticker="ABBA",
        data_snapshot_id="snap-tiingo",
    )

    with pytest.raises(FileExistsError, match="Price snapshot already exists"):
        write_prices_daily_frame(next_ticker, output_root=output_root)

    unexpected_path = (
        output_root
        / "data_snapshot_id=snap-tiingo"
        / "source=tiingo"
        / "year=2026"
        / "ABBA.parquet"
    )
    assert not unexpected_path.exists()
