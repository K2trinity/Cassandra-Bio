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
        ticker="MRNA",
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


def test_run_kline_backtest_rejects_yfinance_for_research_grade_mode(monkeypatch):
    from src.backtest import runner

    monkeypatch.setattr(
        runner,
        "load_ohlc",
        lambda ticker: pd.DataFrame(
            [
                {
                    "date": "2026-04-20",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 1000,
                },
                {
                    "date": "2026-04-21",
                    "open": 101,
                    "high": 102,
                    "low": 100,
                    "close": 102,
                    "volume": 1100,
                },
            ]
        ),
    )

    payload = runner.run_kline_backtest(
        ticker="MRNA",
        start_date="2026-04-20",
        end_date="2026-04-21",
        backtest_mode="research_grade",
        price_source="yfinance",
    )

    assert payload["error"] == (
        "Source yfinance cannot be used for research-grade backtests because "
        "it is not survivorship-bias-free."
    )


def test_run_kline_backtest_exploratory_payload_includes_bias_warning(
    tmp_path,
    monkeypatch,
):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])
    monkeypatch.setattr(
        runner,
        "load_ohlc",
        lambda ticker: pd.DataFrame(
            [
                {
                    "date": "2026-04-20",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 1000,
                },
                {
                    "date": "2026-04-21",
                    "open": 101,
                    "high": 103,
                    "low": 100,
                    "close": 102,
                    "volume": 1100,
                },
                {
                    "date": "2026-04-22",
                    "open": 102,
                    "high": 104,
                    "low": 101,
                    "close": 103,
                    "volume": 1200,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda ticker, start_date, end_date: pd.DataFrame(
            [
                {
                    "id": "evt-1",
                    "date": "2026-04-20",
                    "type": "clinical_readout",
                    "priority": 1,
                    "sentiment": "positive",
                    "ticker_scope": "MRNA",
                    "metadata": {
                        "backtest_eligible": True,
                        "impact_score": 1.0,
                        "confidence_score": 1.0,
                    },
                }
            ]
        ),
    )

    payload = runner.run_kline_backtest(
        ticker="MRNA",
        start_date="2026-04-20",
        end_date="2026-04-22",
        backtest_mode="exploratory",
        price_source="yfinance",
        data_snapshot_id="snap-test",
    )

    assert payload["bias_profile"] == "survivorship_biased"
    assert payload["data_snapshot_id"] == "snap-test"
    assert payload["bias_warnings"] == [
        "Source yfinance is survivorship-biased and is not research-grade."
    ]
