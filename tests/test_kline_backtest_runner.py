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


def test_derive_trades_serializes_daily_exposure_overlays():
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

    trades = _derive_trades(price_window, results)

    assert all("position" not in trade for trade in trades)
    assert trades == [
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

    assert payload == {
        "error": "invalid ticker: use 1-16 letters, numbers, dots, or hyphens"
    }


def test_run_kline_backtest_initializes_events_and_writes_strict_json(
    tmp_path, monkeypatch
):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "open": 100.0,
                "high": 104.0,
                "low": 99.0,
                "close": 103.0,
                "volume": 1000,
            },
            {
                "date": "2026-04-21",
                "open": 103.0,
                "high": 106.0,
                "low": 101.0,
                "close": 105.0,
                "volume": 1100,
            },
            {
                "date": "2026-04-22",
                "open": 105.0,
                "high": 107.0,
                "low": 102.0,
                "close": 106.0,
                "volume": 1200,
            },
        ]
    )
    events = pd.DataFrame(
        [
            {
                "id": "evt-strict-json",
                "date": "2026-04-20",
                "type": "trial_results_posted",
                "priority": 1,
                "sentiment": "positive",
                "source": "clinicaltrials",
                "ownership_status": "owned",
                "metadata": '{"backtest_eligible": true, "confidence_score": 0.9, "impact_score": 0.8}',
            }
        ]
    )
    init_calls: list[bool] = []

    def fake_init_db():
        init_calls.append(True)

    def fake_get_trusted_events(*args, **kwargs):
        return events

    def fake_generate_signals(price_window, event_rows, report_confidence=0.5):
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-04-20"),
                    "signal": 1,
                    "signal_strength": 1.0,
                },
                {
                    "date": pd.Timestamp("2026-04-21"),
                    "signal": 0,
                    "signal_strength": 0.0,
                },
                {
                    "date": pd.Timestamp("2026-04-22"),
                    "signal": 0,
                    "signal_strength": 0.0,
                },
            ]
        )

    def fake_apply_strategy(price_window, signals, **kwargs):
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-04-20"),
                    "position": 0.0,
                    "daily_return": 0.0,
                    "equity": 1.0,
                    "drawdown": 0.0,
                },
                {
                    "date": pd.Timestamp("2026-04-21"),
                    "position": 0.2,
                    "daily_return": 0.01,
                    "equity": 1.01,
                    "drawdown": 0.0,
                },
                {
                    "date": pd.Timestamp("2026-04-22"),
                    "position": 0.0,
                    "daily_return": 0.0,
                    "equity": 1.01,
                    "drawdown": 0.0,
                },
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
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        fake_get_trusted_events,
    )
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])
    monkeypatch.setattr(runner, "generate_signals", fake_generate_signals)
    monkeypatch.setattr(runner, "apply_strategy", fake_apply_strategy)
    monkeypatch.setattr(runner, "compute_metrics", fake_compute_metrics)
    monkeypatch.setattr(
        runner, "compute_event_car", lambda price_window, event_rows: pd.DataFrame()
    )

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
            "source_event_ids": ["evt-strict-json"],
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
            "pnl_pct": 0.05,
        }
    ]
    saved_payload = runner.load_saved_run(payload["run_id"])
    assert saved_payload == payload


def test_derive_trades_prefers_strategy_daily_return_for_pnl_pct():
    from src.backtest.runner import _derive_trades

    price_window = pd.DataFrame(
        [
            {"date": "2026-04-20", "open": 100.0, "close": 101.0},
        ]
    )
    results = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-20"),
                "position": 0.2,
                "daily_return": 0.001798,
            },
        ]
    )

    assert _derive_trades(price_window, results) == [
        {
            "entry_date": "2026-04-20",
            "exit_date": "2026-04-20",
            "direction": "long",
            "size": 0.2,
            "entry_price": 100.0,
            "exit_price": 101.0,
            "pnl_pct": 0.00899,
        }
    ]


def test_attribution_helpers_handle_empty_frames_and_metadata_json():
    from src.backtest.attribution import (
        compute_baseline,
        summarize_events,
        summarize_signals,
    )

    assert summarize_events(pd.DataFrame()) == {
        "by_source": [],
        "by_category": [],
        "by_type": [],
    }
    assert summarize_signals(pd.DataFrame()) == {
        "active_signal_days": 0,
        "long_signal_days": 0,
        "short_signal_days": 0,
        "mean_signal_strength": 0.0,
    }
    assert compute_baseline(pd.DataFrame(), pd.DataFrame()) == {
        "buy_hold_return": None,
        "strategy_return": None,
        "excess_return": None,
    }

    events = pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "type": "market_news",
                "source": "alphavantage",
                "metadata": '{"source_tier": "market_news", "category": "news"}',
            },
            {
                "date": "2026-04-21",
                "type": "macro_policy",
                "source": "gdelt",
                "metadata": '{"source_tier": "macro", "category": "macro"}',
            },
        ]
    )

    summary = summarize_events(events)

    assert summary["by_source"] == [
        {"source": "alphavantage", "count": 1},
        {"source": "gdelt", "count": 1},
    ]
    assert summary["by_category"] == [
        {"category": "macro", "count": 1},
        {"category": "news", "count": 1},
    ]


def test_score_event_uses_phase2_metadata_before_legacy_fallback():
    from src.backtest.signals import score_event

    eligible_event = {
        "type": "unknown_phase2_event",
        "priority": 1,
        "sentiment": "positive",
        "metadata": '{"backtest_eligible": true, "confidence_score": 0.9, "impact_score": 0.8}',
    }
    ineligible_event = {
        "type": "fda_decision",
        "priority": 1,
        "sentiment": "positive",
        "metadata": '{"backtest_eligible": false, "confidence_score": 0.99, "impact_score": 0.99}',
    }
    legacy_event = {
        "type": "fda_decision",
        "priority": 1,
        "sentiment": "positive",
    }

    assert score_event(eligible_event) == 0.72
    assert score_event(ineligible_event) == 0.0
    assert score_event(legacy_event) == 1.0


def test_score_event_ignores_non_finite_phase2_scores_for_strict_json():
    from src.backtest.signals import score_event

    event = {
        "type": "fda_decision",
        "priority": 1,
        "sentiment": "positive",
        "metadata": '{"backtest_eligible": true, "confidence_score": NaN, "impact_score": NaN}',
    }

    assert score_event(event) == 1.0


def test_default_signals_include_phase2_fda_approval_after_enrichment():
    from src.backtest.signals import generate_signals
    from src.kline.event_filter import filter_backtest_events

    ohlc = pd.DataFrame(
        [
            {"date": "2026-04-20"},
            {"date": "2026-04-21"},
        ]
    )
    events = pd.DataFrame(
        [
            {
                "id": "fda-approval",
                "date": "2026-04-20",
                "type": "fda_approval",
                "source": "openfda",
                "ticker": "MRNA",
                "priority": 1,
                "sentiment": "positive",
                "source_ids": ["BLA125514"],
                "metadata": "{}",
            }
        ]
    )

    eligible_events, summary = filter_backtest_events(events)
    signals = generate_signals(ohlc, eligible_events)

    assert summary["eligible_events"] == 1
    assert signals.iloc[0]["signal"] == 1
    assert signals.iloc[0]["signal_strength"] > 0.15


def test_run_kline_backtest_returns_phase2_event_diagnostics(tmp_path, monkeypatch):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "open": 100.0,
                "high": 104.0,
                "low": 99.0,
                "close": 103.0,
                "volume": 1000,
            },
            {
                "date": "2026-04-21",
                "open": 103.0,
                "high": 106.0,
                "low": 101.0,
                "close": 105.0,
                "volume": 1100,
            },
            {
                "date": "2026-04-22",
                "open": 105.0,
                "high": 107.0,
                "low": 102.0,
                "close": 106.0,
                "volume": 1200,
            },
        ]
    )
    events = pd.DataFrame(
        [
            {
                "id": "evt-eligible",
                "date": "2026-04-20",
                "type": "trial_results_posted",
                "priority": 1,
                "sentiment": "positive",
                "source": "clinicaltrials",
                "metadata": '{"backtest_eligible": true, "confidence_score": 0.9, "impact_score": 0.8, "source_tier": "official", "category": "clinical"}',
            },
            {
                "id": "evt-excluded",
                "date": "2026-04-21",
                "type": "macro_economic",
                "priority": 3,
                "sentiment": "neutral",
                "source": "gdelt",
                "metadata": '{"backtest_eligible": false, "confidence_score": 0.4, "impact_score": 0.2, "source_tier": "macro", "category": "macro"}',
            },
        ]
    )

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda *args, **kwargs: events,
    )
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])

    payload = runner.run_kline_backtest(
        ticker="BIIB",
        start_date="2026-04-20",
        end_date="2026-04-22",
    )

    assert payload["event_filter"] == {
        "input_events": 2,
        "eligible_events": 1,
        "excluded_events": 1,
        "min_confidence_score": 0.7,
    }
    assert payload["event_attribution"]["by_source"] == [
        {"source": "clinicaltrials", "count": 1}
    ]
    assert payload["event_attribution"]["by_category"] == [
        {"category": "clinical", "count": 1}
    ]
    assert payload["signal_summary"]["active_signal_days"] == 1
    assert payload["baseline"]["buy_hold_return"] == 0.06
    assert "strategy_return" in payload["baseline"]
    assert payload["signals"][0]["source_event_ids"] == ["evt-eligible"]
    assert all(
        "evt-excluded" not in signal["source_event_ids"]
        for signal in payload["signals"]
    )
    assert runner.load_saved_run(payload["run_id"]) == payload


def test_mock_multifactor_signals_create_multiple_long_signals():
    from src.backtest.mock_dataset import build_mock_factor_frame
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-02") + pd.offsets.BDay(index),
                "open": 100.0 + index,
                "high": 102.0 + index,
                "low": 99.0 + index,
                "close": 101.0 + index + (1.0 if index % 3 == 1 else 0.0),
                "volume": 1_000_000 + index * 25_000,
            }
            for index in range(35)
        ]
    )
    factors = build_mock_factor_frame("MRNA", price_window, min_signal_days=6)

    signals = generate_mock_multifactor_signals(price_window, factors)

    active = signals[signals["signal"] != 0]
    assert len(active) >= 6
    assert set(active["signal"]) == {1}
    assert active["signal_strength"].min() > 0.15


def test_factor_attribution_summarizes_active_signal_drivers():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": 0.32,
                "momentum_factor": 0.10,
                "volume_shock": 0.05,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.12,
                "regime_factor": 0.10,
                "mock_score": 0.69,
            },
            {
                "date": "2025-01-03",
                "event_factor": 0.0,
                "momentum_factor": 0.0,
                "volume_shock": 0.0,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.0,
                "regime_factor": 0.0,
                "mock_score": 0.0,
            },
        ]
    )

    summary = summarize_factor_attribution(factors)

    assert summary["active_factor_days"] == 1
    assert summary["mean_mock_score"] == 0.69
    assert summary["mean_event_factor"] == 0.32
    assert summary["mean_liquidity_factor"] == 0.12


def test_mock_multifactor_signals_deduplicates_factor_dates_with_max_score():
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-01-02")},
            {"date": pd.Timestamp("2025-01-03")},
        ]
    )
    factors = pd.DataFrame(
        [
            {"date": "2025-01-02", "mock_score": 0.10},
            {"date": "2025-01-02", "mock_score": 0.40},
            {"date": "2025-01-03", "mock_score": 0.0},
        ]
    )

    signals = generate_mock_multifactor_signals(price_window, factors)

    assert len(signals) == len(price_window)
    assert signals["date"].is_unique
    assert signals.iloc[0]["signal"] == 1
    assert signals.iloc[0]["signal_strength"] == 0.40


def test_mock_multifactor_signals_zeroes_strength_for_negative_scores():
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame([{"date": pd.Timestamp("2025-01-02")}])
    factors = pd.DataFrame([{"date": "2025-01-02", "mock_score": -0.80}])

    signals = generate_mock_multifactor_signals(price_window, factors)

    assert signals.iloc[0]["signal"] == 0
    assert signals.iloc[0]["signal_strength"] == 0.0


def test_factor_attribution_coerces_string_numeric_values():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": "0.1",
                "momentum_factor": "0.03",
                "volume_shock": "0.02",
                "volatility_penalty": "0.0",
                "liquidity_factor": "0.05",
                "regime_factor": "0.0",
                "mock_score": "0.2",
            }
        ]
    )

    summary = summarize_factor_attribution(factors)

    assert summary["active_factor_days"] == 1
    assert summary["mean_mock_score"] == 0.2
    assert summary["mean_event_factor"] == 0.1


def test_factor_attribution_handles_missing_factor_columns():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": 0.2,
                "momentum_factor": 0.1,
                "volume_shock": 0.0,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.05,
                "mock_score": 0.45,
            }
        ]
    )

    summary = summarize_factor_attribution(factors)

    assert summary["active_factor_days"] == 1
    assert summary["mean_regime_factor"] == 0.0


def test_factor_attribution_coerces_invalid_and_non_finite_values():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": "bad",
                "momentum_factor": float("nan"),
                "volume_shock": float("inf"),
                "volatility_penalty": "-inf",
                "liquidity_factor": None,
                "regime_factor": "0.2",
                "mock_score": float("inf"),
            }
        ]
    )

    summary = summarize_factor_attribution(factors)

    assert summary["active_factor_days"] == 0
    assert summary["mean_mock_score"] == 0.0
    assert summary["mean_event_factor"] == 0.0


def test_factor_attribution_uses_custom_threshold_for_active_days():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": 0.1,
                "momentum_factor": 0.0,
                "volume_shock": 0.0,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.0,
                "regime_factor": 0.0,
                "mock_score": 0.2,
            },
            {
                "date": "2025-01-03",
                "event_factor": 0.3,
                "momentum_factor": 0.0,
                "volume_shock": 0.0,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.0,
                "regime_factor": 0.0,
                "mock_score": 0.5,
            },
        ]
    )

    summary = summarize_factor_attribution(factors, threshold=0.4)

    assert summary["active_factor_days"] == 1
    assert summary["mean_mock_score"] == 0.5
    assert summary["mean_event_factor"] == 0.3


def test_mock_multifactor_signals_handles_empty_and_dateless_factors():
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-01-02")},
            {"date": pd.Timestamp("2025-01-03")},
        ]
    )

    for factors in [
        pd.DataFrame(),
        pd.DataFrame([{"mock_score": 0.8}]),
    ]:
        signals = generate_mock_multifactor_signals(price_window, factors)

        assert len(signals) == len(price_window)
        assert set(signals["signal"]) == {0}
        assert set(signals["signal_strength"]) == {0.0}


def test_factor_attribution_deduplicates_by_date_and_ignores_invalid_dates():
    from src.backtest.multifactor_strategy import summarize_factor_attribution

    factors = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "event_factor": 0.1,
                "momentum_factor": 0.0,
                "volume_shock": 0.0,
                "volatility_penalty": 0.0,
                "liquidity_factor": 0.0,
                "regime_factor": 0.0,
                "mock_score": 0.2,
            },
            {
                "date": "2025-01-02",
                "event_factor": 0.8,
                "momentum_factor": 0.3,
                "volume_shock": 0.2,
                "volatility_penalty": -0.1,
                "liquidity_factor": 0.4,
                "regime_factor": 0.5,
                "mock_score": 0.6,
            },
            {
                "date": "not-a-date",
                "event_factor": 0.9,
                "momentum_factor": 0.9,
                "volume_shock": 0.9,
                "volatility_penalty": 0.9,
                "liquidity_factor": 0.9,
                "regime_factor": 0.9,
                "mock_score": 0.9,
            },
        ]
    )

    summary = summarize_factor_attribution(factors)

    assert summary["active_factor_days"] == 1
    assert summary["mean_mock_score"] == 0.6
    assert summary["mean_event_factor"] == 0.8
    assert summary["mean_regime_factor"] == 0.5


def test_mock_multifactor_signals_matches_timezone_aware_factor_dates():
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame([{"date": pd.Timestamp("2025-01-02")}])
    factors = pd.DataFrame(
        [{"date": "2025-01-02T00:00:00Z", "mock_score": 0.4}]
    )

    signals = generate_mock_multifactor_signals(price_window, factors)

    assert len(signals) == 1
    assert signals.iloc[0]["signal"] == 1
    assert signals.iloc[0]["signal_strength"] == 0.4


def test_mock_multifactor_signals_preserves_local_factor_calendar_dates():
    from src.backtest.multifactor_strategy import generate_mock_multifactor_signals

    price_window = pd.DataFrame([{"date": pd.Timestamp("2025-01-02")}])
    factors = pd.DataFrame(
        [{"date": "2025-01-02T23:30:00-05:00", "mock_score": 0.4}]
    )

    signals = generate_mock_multifactor_signals(price_window, factors)

    assert len(signals) == 1
    assert signals.iloc[0]["signal"] == 1
    assert signals.iloc[0]["signal_strength"] == 0.4


def test_multifactor_helpers_reject_duplicate_factor_columns():
    import pytest

    from src.backtest.multifactor_strategy import (
        generate_mock_multifactor_signals,
        summarize_factor_attribution,
    )

    price_window = pd.DataFrame([{"date": pd.Timestamp("2025-01-02")}])
    factors = pd.DataFrame(
        [["2025-01-02", 0.2, 0.4]],
        columns=["date", "mock_score", "mock_score"],
    )
    empty_factors = pd.DataFrame(columns=["date", "mock_score", "mock_score"])
    empty_attribution = {
        "active_factor_days": 0,
        "mean_mock_score": 0.0,
        "mean_event_factor": 0.0,
        "mean_momentum_factor": 0.0,
        "mean_volume_shock": 0.0,
        "mean_volatility_penalty": 0.0,
        "mean_liquidity_factor": 0.0,
        "mean_regime_factor": 0.0,
    }

    with pytest.raises(ValueError, match="unique columns"):
        generate_mock_multifactor_signals(price_window, factors)

    with pytest.raises(ValueError, match="unique columns"):
        generate_mock_multifactor_signals(price_window, empty_factors)

    assert summarize_factor_attribution(factors) == empty_attribution
    assert summarize_factor_attribution(empty_factors) == empty_attribution


def test_multifactor_helpers_reject_negative_threshold():
    import pytest

    from src.backtest.multifactor_strategy import (
        generate_mock_multifactor_signals,
        summarize_factor_attribution,
    )

    price_window = pd.DataFrame([{"date": pd.Timestamp("2025-01-02")}])
    factors = pd.DataFrame([{"date": "2025-01-02", "mock_score": -0.1}])

    with pytest.raises(ValueError, match="threshold must be non-negative"):
        generate_mock_multifactor_signals(price_window, factors, threshold=-0.2)

    with pytest.raises(ValueError, match="threshold must be non-negative"):
        summarize_factor_attribution(factors, threshold=-0.2)


def test_run_kline_backtest_uses_mock_multifactor_demo_for_a_tickers(
    tmp_path, monkeypatch
):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-02") + pd.offsets.BDay(index),
                "open": 100.0 + index,
                "high": 103.0 + index,
                "low": 99.0 + index,
                "close": 102.0 + index if index % 4 in {1, 2} else 100.5 + index,
                "volume": 1_000_000 + index * 20_000,
            }
            for index in range(45)
        ]
    )

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])
    monkeypatch.setattr(
        runner, "compute_event_car", lambda price_window, event_rows: pd.DataFrame()
    )

    payload = runner.run_kline_backtest(
        ticker="MRNA",
        start_date="2025-01-02",
        end_date="2025-03-31",
    )

    assert payload["strategy"]["id"] == "mock_multifactor_demo"
    assert payload["mock_metadata"]["data_mode"] == "mock"
    assert payload["mock_metadata"]["mock_scope"] == "biotech_mock_v1"
    assert payload["mock_metadata"]["ui_disclosure"] is False
    assert payload["factor_attribution"]["active_factor_days"] >= 6
    assert payload["signal_summary"]["active_signal_days"] >= 6
    assert len(payload["trades"]) >= 5
    assert payload["baseline"]["strategy_return"] > 0


def test_run_kline_backtest_does_not_use_mock_strategy_for_non_a_ticker(
    tmp_path, monkeypatch
):
    from src.backtest import runner

    ohlc = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-02") + pd.offsets.BDay(index),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1_000_000,
            }
            for index in range(5)
        ]
    )

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: ohlc)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    payload = runner.run_kline_backtest(
        ticker="PFE",
        start_date="2025-01-02",
        end_date="2025-01-08",
    )

    assert payload == {"error": "no trusted backtest-eligible events in date range"}


def test_run_kline_backtest_rejects_mock_strategy_when_not_mock_mode(
    tmp_path, monkeypatch
):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)

    payload = runner.run_kline_backtest(
        ticker="MRNA",
        start_date="2025-01-02",
        end_date="2025-01-08",
        strategy_id="mock_multifactor_demo",
        data_mode="real",
    )

    assert payload["error"] == "mock_multifactor_demo requires data_mode='mock'"


def test_run_kline_backtest_rejects_explicit_mock_strategy_for_non_a_ticker(
    tmp_path, monkeypatch
):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)

    payload = runner.run_kline_backtest(
        ticker="PFE",
        start_date="2025-01-02",
        end_date="2025-01-08",
        strategy_id="mock_multifactor_demo",
        data_mode="mock",
    )

    assert (
        payload["error"]
        == "mock_multifactor_demo requires mock_scope='biotech_mock_v1'"
    )


def test_align_events_to_trading_dates_handles_mixed_timezone_inputs():
    from src.backtest.signals import align_events_to_trading_dates

    ohlc = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2025-01-03 09:30:00", tz="America/New_York"),
                pd.Timestamp("2025-01-06 09:30:00", tz="America/New_York"),
            ]
        }
    )
    events = pd.DataFrame(
        [
            {"event_id": "weekend", "date": "2025-01-04"},
            {"event_id": "invalid", "date": "not-a-date"},
            {"event_id": "after-window", "date": "2025-01-07"},
        ]
    )

    aligned = align_events_to_trading_dates(events, ohlc)

    assert aligned["event_id"].tolist() == ["weekend"]
    assert aligned.loc[0, "date"] == pd.Timestamp("2025-01-06")
    assert aligned.loc[0, "original_event_date"] == pd.Timestamp("2025-01-04")


def test_align_events_to_trading_dates_returns_copy_when_date_column_missing():
    from src.backtest.signals import align_events_to_trading_dates

    events_without_date = pd.DataFrame(
        {"event_id": ["evt-1"], "type": ["clinical_readout"]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-01-04")], name="date"),
    )
    ohlc = pd.DataFrame({"date": [pd.Timestamp("2025-01-06")]})

    aligned = align_events_to_trading_dates(events_without_date, ohlc)

    assert aligned is not events_without_date
    pd.testing.assert_frame_equal(aligned, events_without_date.copy())

    events = pd.DataFrame({"event_id": ["evt-1"], "date": [pd.Timestamp("2025-01-04")]})
    ohlc_without_date = pd.DataFrame(
        {"close": [101.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-01-06")], name="date"),
    )

    aligned = align_events_to_trading_dates(events, ohlc_without_date)

    assert aligned is not events
    pd.testing.assert_frame_equal(aligned, events.copy())
