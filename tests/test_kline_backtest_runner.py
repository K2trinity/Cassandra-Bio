from __future__ import annotations

import math

import pandas as pd


def test_json_safe_number_rejects_non_finite_values():
    from src.backtest.runner import _json_safe_number

    assert _json_safe_number(float("inf")) is None
    assert _json_safe_number(float("-inf")) is None
    assert _json_safe_number(float("nan")) is None
    assert _json_safe_number(1.25) == 1.25


def test_load_saved_run_rejects_non_generated_ids(tmp_path, monkeypatch):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)

    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    assert runner.load_saved_run("../outside") is None
    assert runner.load_saved_run("run-123") is None


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
    saved_payload = runner.load_saved_run(payload["run_id"])
    assert saved_payload == payload
