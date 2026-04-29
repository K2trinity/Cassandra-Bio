from __future__ import annotations

import json

import pandas as pd


def price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
            },
            {
                "date": "2025-01-02",
                "open": 101.0,
                "high": 106.0,
                "low": 100.0,
                "close": 105.0,
            },
            {
                "date": "2025-01-03",
                "open": 105.0,
                "high": 107.0,
                "low": 103.0,
                "close": 104.0,
            },
            {
                "date": "2025-01-04",
                "open": 104.0,
                "high": 108.0,
                "low": 102.0,
                "close": 107.0,
            },
            {
                "date": "2025-01-05",
                "open": 107.0,
                "high": 109.0,
                "low": 105.0,
                "close": 108.0,
            },
        ]
    )


def trusted_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": "trusted-event",
                "date": "2025-01-02",
                "type": "trial_results_posted",
                "priority": 1,
                "ticker": "MRNA",
                "ticker_scope": "MRNA",
                "sentiment": "positive",
                "source": "clinicaltrials",
                "ownership_status": "owned",
                "trust_status": "trusted",
                "schema_version": 2,
                "metadata": {"backtest_eligible": True},
            }
        ]
    )


def test_backtest_reads_trusted_events_only(tmp_path, monkeypatch):
    from src.backtest import runner

    called: list[tuple[str, str, str]] = []

    def fake_trusted_events(
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        called.append((ticker, start_date, end_date))
        return trusted_events()

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: price_frame())
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        fake_trusted_events,
    )
    monkeypatch.setattr(runner, "get_fetch_log_entries", lambda ticker: [])

    result = runner.run_kline_backtest("MRNA", "2025-01-01", "2025-01-05")

    assert called == [("MRNA", "2025-01-01", "2025-01-05")]
    assert result["input_event_ids"] == ["trusted-event"]
    assert result["trust_summary"]["trusted_event_count"] == 1
    assert (tmp_path / "index.json").exists()


def test_backtest_returns_error_without_trusted_events(tmp_path, monkeypatch):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: price_frame())
    monkeypatch.setattr(
        runner,
        "get_trusted_events_for_backtest",
        lambda ticker, start_date, end_date: pd.DataFrame(),
    )

    result = runner.run_kline_backtest("MRNA", "2025-01-01", "2025-01-05")

    assert result == {"error": "no trusted backtest-eligible events in date range"}
    assert not (tmp_path / "index.json").exists()


def test_backtest_provider_loads_latest_indexed_run(tmp_path):
    from src.kline.providers.backtest_provider import BacktestResultProvider

    run_id = "20250102_120000_deadbeef"
    payload = {"run_id": run_id, "ticker": "MRNA", "metrics": {"sharpe": 1.2}}
    (tmp_path / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps({"latest_by_ticker": {"MRNA": {"run_id": run_id}}}),
        encoding="utf-8",
    )

    assert BacktestResultProvider(results_dir=tmp_path).load_last_run("MRNA") == payload
