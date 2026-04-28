from __future__ import annotations

import math

import pandas as pd


def test_json_safe_number_rejects_non_finite_values():
    from src.backtest.runner import _json_safe_number

    assert _json_safe_number(float("inf")) is None
    assert _json_safe_number(float("-inf")) is None
    assert _json_safe_number(float("nan")) is None
    assert _json_safe_number(1.25) == 1.25


def test_serialize_signals_preserves_zero_signal_days_and_attaches_event_ids():
    from src.backtest.runner import _serialize_signals

    signals = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-20"), "signal": 1, "signal_strength": 0.75},
            {"date": pd.Timestamp("2026-04-21"), "signal": 0, "signal_strength": 0.0},
            {"date": pd.Timestamp("2026-04-22"), "signal": -1, "signal_strength": 0.5},
        ]
    )
    events = pd.DataFrame(
        [
            {"event_id": "evt-1", "date": "2026-04-20"},
            {"id": "evt-2", "date": "2026-04-20"},
            {"event_id": "evt-3", "date": "2026-04-22"},
        ]
    )

    assert _serialize_signals(signals, events) == [
        {
            "date": "2026-04-20",
            "signal": 1,
            "signal_strength": 0.75,
            "source_event_ids": ["evt-1", "evt-2"],
        },
        {
            "date": "2026-04-21",
            "signal": 0,
            "signal_strength": 0.0,
            "source_event_ids": [],
        },
        {
            "date": "2026-04-22",
            "signal": -1,
            "signal_strength": 0.5,
            "source_event_ids": ["evt-3"],
        },
    ]


def test_derive_trades_handles_exits_flips_and_open_trade_closeout():
    from src.backtest.runner import _derive_trades

    price_window = pd.DataFrame(
        [
            {"date": "2026-04-20", "open": 100.0, "close": 110.0},
            {"date": "2026-04-21", "open": 111.0, "close": 120.0},
            {"date": "2026-04-22", "open": 119.0, "close": 115.0},
            {"date": "2026-04-23", "open": 114.0, "close": 108.0},
            {"date": "2026-04-24", "open": 107.0, "close": 109.0},
            {"date": "2026-04-25", "open": 108.0, "close": 104.0},
        ]
    )
    results = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-20"), "position": 0.0},
            {"date": pd.Timestamp("2026-04-21"), "position": 0.2},
            {"date": pd.Timestamp("2026-04-22"), "position": 0.2},
            {"date": pd.Timestamp("2026-04-23"), "position": 0.0},
            {"date": pd.Timestamp("2026-04-24"), "position": -0.2},
            {"date": pd.Timestamp("2026-04-25"), "position": 0.2},
        ]
    )

    assert _derive_trades(price_window, results) == [
        {
            "entry_date": "2026-04-21",
            "exit_date": "2026-04-21",
            "direction": "long",
            "size": 0.2,
            "entry_price": 111.0,
            "exit_price": 120.0,
            "pnl_pct": 0.081081,
        },
        {
            "entry_date": "2026-04-22",
            "exit_date": "2026-04-22",
            "direction": "long",
            "size": 0.2,
            "entry_price": 119.0,
            "exit_price": 115.0,
            "pnl_pct": -0.033613,
        },
        {
            "entry_date": "2026-04-24",
            "exit_date": "2026-04-24",
            "direction": "short",
            "size": 0.2,
            "entry_price": 107.0,
            "exit_price": 109.0,
            "pnl_pct": -0.018692,
        },
        {
            "entry_date": "2026-04-25",
            "exit_date": "2026-04-25",
            "direction": "long",
            "size": 0.2,
            "entry_price": 108.0,
            "exit_price": 104.0,
            "pnl_pct": -0.037037,
        },
    ]


def test_load_saved_run_rejects_non_generated_ids(tmp_path, monkeypatch):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)

    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    assert runner.load_saved_run("../outside") is None
    assert runner.load_saved_run("run-123") is None


def test_load_saved_run_returns_none_for_corrupt_json(tmp_path, monkeypatch):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    run_id = "20260428_120000_deadbeef"
    (tmp_path / f"{run_id}.json").write_text("{", encoding="utf-8")

    assert runner.load_saved_run(run_id) is None


def test_run_kline_backtest_rejects_invalid_ticker_without_loading(monkeypatch):
    from src.backtest import runner

    def fail_load_ohlc(ticker: str):
        raise AssertionError("load_ohlc should not be called for invalid ticker")

    monkeypatch.setattr(runner, "load_ohlc", fail_load_ohlc)

    payload = runner.run_kline_backtest(
        ticker="../BIIB",
        start_date="2026-04-20",
        end_date="2026-04-22",
    )

    assert payload == {"error": "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"}


def test_run_kline_backtest_initializes_events_and_writes_strict_json(tmp_path, monkeypatch):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {"date": "2026-04-20", "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0, "volume": 1000},
            {"date": "2026-04-21", "open": 103.0, "high": 106.0, "low": 101.0, "close": 105.0, "volume": 1100},
            {"date": "2026-04-22", "open": 105.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 1200},
        ]
    )
    events = pd.DataFrame()
    init_calls: list[bool] = []

    def fake_init_db():
        init_calls.append(True)

    def fake_get_events(*args, **kwargs):
        return events

    def fake_generate_signals(price_window, event_rows, report_confidence=0.5):
        return pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-20"), "signal": 1, "signal_strength": 1.0},
                {"date": pd.Timestamp("2026-04-21"), "signal": 0, "signal_strength": 0.0},
                {"date": pd.Timestamp("2026-04-22"), "signal": 0, "signal_strength": 0.0},
            ]
        )

    def fake_apply_strategy(price_window, signals, **kwargs):
        return pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-20"), "position": 0.0, "daily_return": 0.0, "equity": 1.0, "drawdown": 0.0},
                {"date": pd.Timestamp("2026-04-21"), "position": 0.2, "daily_return": 0.01, "equity": 1.01, "drawdown": 0.0},
                {"date": pd.Timestamp("2026-04-22"), "position": 0.0, "daily_return": 0.0, "equity": 1.01, "drawdown": 0.0},
            ]
        )

    def fake_compute_metrics(results):
        return {
            "layer3_strategy": {
                "sharpe_ratio": 1.5,
                "annualized_return": 0.12,
                "max_drawdown": -0.03,
                "win_rate": 1.0,
                "profit_factor": math.inf,
            }
        }

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(runner, "init_db", fake_init_db)
    monkeypatch.setattr(runner, "get_events", fake_get_events)
    monkeypatch.setattr(runner, "generate_signals", fake_generate_signals)
    monkeypatch.setattr(runner, "apply_strategy", fake_apply_strategy)
    monkeypatch.setattr(runner, "compute_metrics", fake_compute_metrics)
    monkeypatch.setattr(runner, "compute_event_car", lambda price_window, event_rows: pd.DataFrame())

    payload = runner.run_kline_backtest(
        ticker="BIIB",
        start_date="2026-04-20",
        end_date="2026-04-22",
    )

    assert init_calls == [True]
    assert payload["metrics"]["profit_factor"] is None
    assert payload["equity_curve"] == [
        {"date": "2026-04-20", "equity": 1.0},
        {"date": "2026-04-21", "equity": 1.01},
        {"date": "2026-04-22", "equity": 1.01},
    ]
    assert payload["signals"] == [
        {
            "date": "2026-04-20",
            "signal": 1,
            "signal_strength": 1.0,
            "source_event_ids": [],
        },
        {
            "date": "2026-04-21",
            "signal": 0,
            "signal_strength": 0.0,
            "source_event_ids": [],
        },
        {
            "date": "2026-04-22",
            "signal": 0,
            "signal_strength": 0.0,
            "source_event_ids": [],
        },
    ]
    assert payload["trades"] == [
        {
            "entry_date": "2026-04-21",
            "exit_date": "2026-04-21",
            "direction": "long",
            "size": 0.2,
            "entry_price": 103.0,
            "exit_price": 105.0,
            "pnl_pct": 0.019417,
        }
    ]
    saved_payload = runner.load_saved_run(payload["run_id"])
    assert saved_payload == payload
