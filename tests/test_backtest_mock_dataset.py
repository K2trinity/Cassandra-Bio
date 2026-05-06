from __future__ import annotations

import pandas as pd


def _price_window() -> pd.DataFrame:
    rows = []
    price = 100.0
    for index in range(30):
        date = pd.Timestamp("2025-01-02") + pd.offsets.BDay(index)
        open_price = price
        close_price = price + (2.0 if index % 4 in {1, 2} else -0.5)
        rows.append(
            {
                "date": date,
                "open": open_price,
                "high": max(open_price, close_price) + 1.0,
                "low": min(open_price, close_price) - 1.0,
                "close": close_price,
                "volume": 1_000_000 + index * 10_000,
            }
        )
        price = close_price
    return pd.DataFrame(rows)


def _sparse_positive_price_window() -> pd.DataFrame:
    rows = []
    for index in range(10):
        date = pd.Timestamp("2025-01-02") + pd.offsets.BDay(index)
        open_price = 100.0 + index
        close_price = open_price + (2.0 if index == 5 else -1.0)
        rows.append(
            {
                "date": date,
                "open": open_price,
                "high": max(open_price, close_price) + 1.0,
                "low": min(open_price, close_price) - 1.0,
                "close": close_price,
                "volume": 1_000_000 + index * 10_000,
            }
        )
    return pd.DataFrame(rows)


def test_mock_universe_is_limited_to_four_demo_tickers():
    from src.backtest.mock_dataset import MOCK_BACKTEST_TICKERS, is_mock_backtest_ticker

    assert MOCK_BACKTEST_TICKERS == ("MRNA", "JNJ", "LLY", "ABBA")
    assert is_mock_backtest_ticker("MRNA")
    assert is_mock_backtest_ticker("abba")
    assert not is_mock_backtest_ticker("PFE")


def test_ticker_normalization_handles_null_like_values():
    from src.backtest.mock_dataset import is_mock_backtest_ticker, normalize_ticker

    assert normalize_ticker(None) == ""
    assert normalize_ticker(pd.NA) == ""
    assert is_mock_backtest_ticker(pd.NA) is False


def test_mock_run_metadata_marks_backend_only_demo_scope():
    from src.backtest.mock_dataset import mock_run_metadata

    assert mock_run_metadata("MRNA") == {
        "data_mode": "mock",
        "mock_scope": "biotech_mock_v1",
        "synthetic": True,
        "ui_disclosure": False,
        "positive_demo_expected": True,
        "synthetic_hindsight_fixture": True,
        "ticker": "MRNA",
    }


def test_build_mock_factor_frame_creates_multiple_high_score_rows():
    from src.backtest.mock_dataset import build_mock_factor_frame

    factors = build_mock_factor_frame("MRNA", _price_window(), min_signal_days=5)

    assert list(factors.columns) == [
        "date",
        "event_factor",
        "momentum_factor",
        "volume_shock",
        "volatility_penalty",
        "liquidity_factor",
        "regime_factor",
        "mock_score",
    ]
    assert len(factors[factors["mock_score"] > 0.15]) >= 5
    assert factors["mock_score"].max() <= 1.0
    assert factors["volatility_penalty"].max() <= 0.0


def test_build_mock_factor_frame_returns_empty_frame_for_unsupported_ticker():
    from src.backtest.mock_dataset import build_mock_factor_frame

    factors = build_mock_factor_frame("PFE", _price_window(), min_signal_days=5)

    assert list(factors.columns) == [
        "date",
        "event_factor",
        "momentum_factor",
        "volume_shock",
        "volatility_penalty",
        "liquidity_factor",
        "regime_factor",
        "mock_score",
    ]
    assert factors.empty


def test_build_mock_factor_frame_returns_empty_frame_for_short_signal_window():
    from src.backtest.mock_dataset import build_mock_factor_frame

    factors = build_mock_factor_frame("MRNA", _price_window().head(4), min_signal_days=5)

    assert list(factors.columns) == [
        "date",
        "event_factor",
        "momentum_factor",
        "volume_shock",
        "volatility_penalty",
        "liquidity_factor",
        "regime_factor",
        "mock_score",
    ]
    assert factors.empty


def test_build_mock_factor_frame_tops_up_sparse_positive_candidates():
    from src.backtest.mock_dataset import build_mock_factor_frame

    factors = build_mock_factor_frame("MRNA", _sparse_positive_price_window(), min_signal_days=5)

    assert list(factors.columns) == [
        "date",
        "event_factor",
        "momentum_factor",
        "volume_shock",
        "volatility_penalty",
        "liquidity_factor",
        "regime_factor",
        "mock_score",
    ]
    assert len(factors[factors["mock_score"] > 0.15]) >= 5
