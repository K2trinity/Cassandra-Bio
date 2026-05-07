# Biotech Mock Backtest A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the A path: a K-line single-ticker mock multi-factor backtest for `MRNA`, `JNJ`, `LLY`, and `ABBA` that creates multiple trades and a positive demo equity curve while keeping the mock nature out of the UI and explicit in backend metadata.

**Architecture:** Add a mock-only strategy path behind the existing K-line backtest endpoint. The runner chooses `mock_multifactor_demo` by default only for the four-ticker mock universe, generates synthetic multi-factor signal inputs before strategy execution, and stores mock metadata in the result payload. B/C work remains out of scope for this plan.

**Tech Stack:** Python 3.11, pandas, pytest, Flask, vanilla JS K-line workspace, existing JSON result store.

---

## Scope

This plan implements only A from `docs/superpowers/specs/2026-05-06-biotech-backtest-lab-design.md`.

## 2026-05-06 Implementation Status Update

Current worktree status after the K-line portfolio UI optimization audit:

- A-path mock universe, strategy registry guardrails, multi-factor signals, factor attribution, hidden backend mock metadata, and UI non-disclosure tests are implemented.
- The A-path execution model now uses `holding_period_days = 5` by default for `mock_multifactor_demo`, while single-run and portfolio APIs accept a validated `holding_period_days` override from `1..60`.
- Single-run payloads now record `risk_parameters` with stop loss, max position, slippage, and holding period. Portfolio runs propagate the same holding period into every constituent run and return sanitized portfolio diagnostics.
- The current four-ticker smoke output for `2025-01-02` through `2025-03-31` is approximately `+31.55%` per ticker and portfolio, with 36 daily exposure overlays per constituent and equity changes across January, February, and March.
- Verification completed in this worktree:
  - `pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp\codex-final-active` -> `99 passed`
  - `pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_backtest_runner.py tests/test_kline_backtest_trusted_inputs.py tests/test_kline_static_bundle.py tests/test_market_data_service.py tests/test_event_ingestion_service.py tests/test_event_ingestion_trust_boundary.py tests/test_kline_event_filter.py tests/test_kline_event_trust_db.py -q --basetemp .pytest_tmp\codex-final-wide-existing` -> `195 passed`
  - `npm run build` from `src/kline` -> TypeScript and Vite build completed.
- The larger B/C items in the project spec remain out of this A-path implementation: DuckDB/Parquet snapshot layer, Backtest Lab page, split enforcement, real multifactor B runner, ML feature matrix, and `ml_probability`.

In scope:

- mock universe: `MRNA`, `JNJ`, `LLY`, `ABBA`
- hidden default strategy selection for K-line single-ticker backtests
- mock multi-factor signals with more than sparse event-day exposure
- positive equity curves for mock runs
- factor attribution display in the existing Backtest tab
- backend metadata marking the run as mock
- tests proving B/C guardrails are not bypassed by the mock strategy

Out of scope:

- DuckDB/Parquet snapshot layer
- Backtest Lab page
- universe portfolio runner
- ML feature matrix or model training
- real-data strategy optimization

---

## File Structure

- Create `src/backtest/mock_dataset.py`
  - Owns the A mock universe constants and run metadata.
  - Builds deterministic mock factor rows for a given ticker and OHLC window.
  - Selects mock demo signal dates from the OHLC window as synthetic demonstration inputs.

- Create `src/backtest/strategy_registry.py`
  - Defines strategy ids.
  - Resolves the default K-line strategy for a ticker.
  - Guards `mock_multifactor_demo` so it can run only with `data_mode = "mock"` and `mock_scope = "biotech_mock_v1"`.

- Create `src/backtest/multifactor_strategy.py`
  - Converts factor rows into signal rows.
  - Computes factor attribution for the result payload.
  - Contains no UI logic and no event database calls.

- Modify `src/backtest/runner.py`
  - Add optional `strategy_id` and `data_mode` parameters to `run_kline_backtest()`.
  - Resolve mock strategy defaults for the four A tickers.
  - Use `mock_multifactor_demo` signals when selected.
  - Add `strategy`, `mock_metadata`, and `factor_attribution` to payload.

- Modify `src/kline/routes.py`
  - Accept optional `strategy_id` from JSON without exposing it in the UI.
  - Keep existing request validation.

- Modify `static/kline/workspace.js`
  - Render `factor_attribution`.
  - Do not render `mock`, `synthetic`, `data_mode`, or `positive_demo_expected` text.

- Modify `tests/test_kline_backtest_runner.py`
  - Add runner-level A tests.

- Create `tests/test_backtest_mock_dataset.py`
  - Add tests for mock universe metadata and factor generation.

- Create `tests/test_backtest_strategy_registry.py`
  - Add guardrail tests for mock-only strategy access.

- Modify `tests/test_kline_workspace_js.py`
  - Add frontend rendering tests for factor attribution and no mock disclosure text.

- Modify `tests/test_kline_web_integration.py`
  - Add API-level tests proving `/api/backtest/run` returns mock metadata for A but no rendered HTML mock disclosure.

---

## Task 1: Mock Dataset Contract

**Files:**
- Create: `src/backtest/mock_dataset.py`
- Test: `tests/test_backtest_mock_dataset.py`

- [ ] **Step 1: Write failing tests for the mock universe and metadata**

Create `tests/test_backtest_mock_dataset.py`:

```python
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


def test_mock_universe_is_limited_to_four_demo_tickers():
    from src.backtest.mock_dataset import MOCK_BACKTEST_TICKERS, is_mock_backtest_ticker

    assert MOCK_BACKTEST_TICKERS == ("MRNA", "JNJ", "LLY", "ABBA")
    assert is_mock_backtest_ticker("MRNA")
    assert is_mock_backtest_ticker("abba")
    assert not is_mock_backtest_ticker("PFE")


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
```

- [ ] **Step 2: Run the tests and verify they fail for missing module**

Run:

```powershell
pytest tests/test_backtest_mock_dataset.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.backtest.mock_dataset'
```

- [ ] **Step 3: Implement the mock dataset module**

Create `src/backtest/mock_dataset.py`:

```python
from __future__ import annotations

from typing import Final

import pandas as pd

MOCK_BACKTEST_TICKERS: Final[tuple[str, ...]] = ("MRNA", "JNJ", "LLY", "ABBA")
MOCK_SCOPE: Final[str] = "biotech_mock_v1"
MOCK_DATA_MODE: Final[str] = "mock"


def normalize_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def is_mock_backtest_ticker(ticker: object) -> bool:
    return normalize_ticker(ticker) in MOCK_BACKTEST_TICKERS


def mock_run_metadata(ticker: object) -> dict[str, object]:
    return {
        "data_mode": MOCK_DATA_MODE,
        "mock_scope": MOCK_SCOPE,
        "synthetic": True,
        "ui_disclosure": False,
        "positive_demo_expected": True,
        "synthetic_hindsight_fixture": True,
        "ticker": normalize_ticker(ticker),
    }


def build_mock_factor_frame(
    ticker: object,
    price_window: pd.DataFrame,
    min_signal_days: int = 8,
) -> pd.DataFrame:
    """Build mock-only factor rows from controlled demonstration inputs.

    The selected rows are synthetic hindsight fixtures and must remain limited
    to the A demo path. B/C must not call this function.
    """
    if price_window.empty or len(price_window) < 3:
        return _empty_factor_frame()

    rows = price_window[["date", "open", "close", "volume"]].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    rows = rows.sort_values("date").reset_index(drop=True)
    rows["next_open"] = rows["open"].shift(-1)
    rows["next_close"] = rows["close"].shift(-1)
    rows["next_intraday_return"] = rows["next_close"] / rows["next_open"].clip(lower=0.01) - 1
    rows["ret_3d"] = rows["close"].pct_change(3).fillna(0)
    rows["volume_ratio"] = rows["volume"] / rows["volume"].rolling(5, min_periods=1).mean().clip(lower=1)

    candidates = rows[rows["next_intraday_return"] > 0].copy()
    if candidates.empty:
        candidates = rows.iloc[:-1].copy()
    candidates = candidates.sort_values(
        ["next_intraday_return", "volume_ratio"],
        ascending=[False, False],
    ).head(max(1, min_signal_days))

    factors = rows[["date"]].copy()
    factors["event_factor"] = 0.0
    factors["momentum_factor"] = 0.0
    factors["volume_shock"] = 0.0
    factors["volatility_penalty"] = 0.0
    factors["liquidity_factor"] = 0.0
    factors["regime_factor"] = 0.0

    selected_index = candidates.index
    factors.loc[selected_index, "event_factor"] = 0.32
    factors.loc[selected_index, "momentum_factor"] = rows.loc[selected_index, "ret_3d"].clip(lower=0.0, upper=0.08) * 2.0
    factors.loc[selected_index, "volume_shock"] = (rows.loc[selected_index, "volume_ratio"] - 1.0).clip(lower=0.0, upper=0.25)
    factors.loc[selected_index, "liquidity_factor"] = 0.12
    factors.loc[selected_index, "regime_factor"] = 0.10
    factors["mock_score"] = (
        factors["event_factor"]
        + factors["momentum_factor"]
        + factors["volume_shock"]
        + factors["volatility_penalty"]
        + factors["liquidity_factor"]
        + factors["regime_factor"]
    ).clip(lower=0.0, upper=1.0)
    return factors[
        [
            "date",
            "event_factor",
            "momentum_factor",
            "volume_shock",
            "volatility_penalty",
            "liquidity_factor",
            "regime_factor",
            "mock_score",
        ]
    ]


def _empty_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "event_factor",
            "momentum_factor",
            "volume_shock",
            "volatility_penalty",
            "liquidity_factor",
            "regime_factor",
            "mock_score",
        ]
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```powershell
pytest tests/test_backtest_mock_dataset.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add src/backtest/mock_dataset.py tests/test_backtest_mock_dataset.py
git commit -m "feat: add mock biotech backtest dataset"
```

---

## Task 2: Strategy Registry Guardrails

**Files:**
- Create: `src/backtest/strategy_registry.py`
- Test: `tests/test_backtest_strategy_registry.py`

- [ ] **Step 1: Write failing guardrail tests**

Create `tests/test_backtest_strategy_registry.py`:

```python
from __future__ import annotations

import pytest


def test_default_strategy_uses_mock_demo_only_for_a_universe():
    from src.backtest.strategy_registry import default_strategy_for_kline

    assert default_strategy_for_kline("MRNA") == "mock_multifactor_demo"
    assert default_strategy_for_kline("JNJ") == "mock_multifactor_demo"
    assert default_strategy_for_kline("LLY") == "mock_multifactor_demo"
    assert default_strategy_for_kline("ABBA") == "mock_multifactor_demo"
    assert default_strategy_for_kline("PFE") == "event_baseline"


def test_mock_strategy_requires_mock_data_mode_and_scope():
    from src.backtest.strategy_registry import StrategyAccessError, validate_strategy_access

    validate_strategy_access(
        strategy_id="mock_multifactor_demo",
        data_mode="mock",
        mock_scope="biotech_mock_v1",
    )

    with pytest.raises(StrategyAccessError, match="mock_multifactor_demo"):
        validate_strategy_access(
            strategy_id="mock_multifactor_demo",
            data_mode="real",
            mock_scope=None,
        )

    with pytest.raises(StrategyAccessError, match="biotech_mock_v1"):
        validate_strategy_access(
            strategy_id="mock_multifactor_demo",
            data_mode="mock",
            mock_scope="biotech_four_v1",
        )


def test_real_strategies_do_not_need_mock_scope():
    from src.backtest.strategy_registry import validate_strategy_access

    validate_strategy_access(
        strategy_id="event_baseline",
        data_mode="real",
        mock_scope=None,
    )
    validate_strategy_access(
        strategy_id="multifactor_score",
        data_mode="real",
        mock_scope=None,
    )
```

- [ ] **Step 2: Run the tests and verify they fail for missing module**

Run:

```powershell
pytest tests/test_backtest_strategy_registry.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.backtest.strategy_registry'
```

- [ ] **Step 3: Implement the registry**

Create `src/backtest/strategy_registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.backtest.mock_dataset import MOCK_DATA_MODE, MOCK_SCOPE, is_mock_backtest_ticker

EVENT_BASELINE: Final[str] = "event_baseline"
MOCK_MULTIFACTOR_DEMO: Final[str] = "mock_multifactor_demo"
MULTIFACTOR_SCORE: Final[str] = "multifactor_score"
ML_PROBABILITY: Final[str] = "ml_probability"

KNOWN_STRATEGIES: Final[set[str]] = {
    EVENT_BASELINE,
    MOCK_MULTIFACTOR_DEMO,
    MULTIFACTOR_SCORE,
    ML_PROBABILITY,
}


class StrategyAccessError(ValueError):
    """Raised when a strategy is not valid for the requested data mode."""


@dataclass(frozen=True)
class StrategyContext:
    strategy_id: str
    data_mode: str
    mock_scope: str | None


def default_strategy_for_kline(ticker: object) -> str:
    if is_mock_backtest_ticker(ticker):
        return MOCK_MULTIFACTOR_DEMO
    return EVENT_BASELINE


def validate_strategy_access(
    strategy_id: str,
    data_mode: str,
    mock_scope: str | None,
) -> None:
    if strategy_id not in KNOWN_STRATEGIES:
        raise StrategyAccessError(f"unknown strategy: {strategy_id}")

    if strategy_id != MOCK_MULTIFACTOR_DEMO:
        return

    if data_mode != MOCK_DATA_MODE:
        raise StrategyAccessError(
            "mock_multifactor_demo requires data_mode='mock'"
        )
    if mock_scope != MOCK_SCOPE:
        raise StrategyAccessError(
            "mock_multifactor_demo requires mock_scope='biotech_mock_v1'"
        )
```

- [ ] **Step 4: Run the registry tests**

Run:

```powershell
pytest tests/test_backtest_strategy_registry.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/backtest/strategy_registry.py tests/test_backtest_strategy_registry.py
git commit -m "feat: guard mock backtest strategy access"
```

---

## Task 3: Mock Multi-Factor Strategy

**Files:**
- Create: `src/backtest/multifactor_strategy.py`
- Test: `tests/test_kline_backtest_runner.py`

- [ ] **Step 1: Add failing tests for multi-factor signal generation**

Append to `tests/test_kline_backtest_runner.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail for missing module**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_mock_multifactor_signals_create_multiple_long_signals tests/test_kline_backtest_runner.py::test_factor_attribution_summarizes_active_signal_drivers -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.backtest.multifactor_strategy'
```

- [ ] **Step 3: Implement the multi-factor strategy helpers**

Create `src/backtest/multifactor_strategy.py`:

```python
from __future__ import annotations

import math
from typing import Any

import pandas as pd

FACTOR_COLUMNS = [
    "event_factor",
    "momentum_factor",
    "volume_shock",
    "volatility_penalty",
    "liquidity_factor",
    "regime_factor",
]


def generate_mock_multifactor_signals(
    price_window: pd.DataFrame,
    factors: pd.DataFrame,
    threshold: float = 0.15,
) -> pd.DataFrame:
    signals = price_window[["date"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    signals = signals.merge(_factor_scores(factors), on="date", how="left")
    signals["mock_score"] = signals["mock_score"].fillna(0.0)
    signals["signal"] = 0
    signals.loc[signals["mock_score"] > threshold, "signal"] = 1
    signals["signal_strength"] = signals["mock_score"].abs().clip(upper=1.0)
    return signals[["date", "signal", "signal_strength"]]


def summarize_factor_attribution(factors: pd.DataFrame) -> dict[str, Any]:
    if factors.empty or "mock_score" not in factors.columns:
        return {
            "active_factor_days": 0,
            "mean_mock_score": 0.0,
            "mean_event_factor": 0.0,
            "mean_momentum_factor": 0.0,
            "mean_volume_shock": 0.0,
            "mean_volatility_penalty": 0.0,
            "mean_liquidity_factor": 0.0,
            "mean_regime_factor": 0.0,
        }

    rows = factors.copy()
    active = rows[rows["mock_score"] > 0.15]
    if active.empty:
        return {
            "active_factor_days": 0,
            "mean_mock_score": 0.0,
            "mean_event_factor": 0.0,
            "mean_momentum_factor": 0.0,
            "mean_volume_shock": 0.0,
            "mean_volatility_penalty": 0.0,
            "mean_liquidity_factor": 0.0,
            "mean_regime_factor": 0.0,
        }

    return {
        "active_factor_days": int(len(active)),
        "mean_mock_score": _round_float(active["mock_score"].mean()),
        "mean_event_factor": _round_float(active["event_factor"].mean()),
        "mean_momentum_factor": _round_float(active["momentum_factor"].mean()),
        "mean_volume_shock": _round_float(active["volume_shock"].mean()),
        "mean_volatility_penalty": _round_float(active["volatility_penalty"].mean()),
        "mean_liquidity_factor": _round_float(active["liquidity_factor"].mean()),
        "mean_regime_factor": _round_float(active["regime_factor"].mean()),
    }


def _factor_scores(factors: pd.DataFrame) -> pd.DataFrame:
    if factors.empty:
        return pd.DataFrame(columns=["date", "mock_score"])
    rows = factors[["date", "mock_score"]].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    rows["mock_score"] = pd.to_numeric(rows["mock_score"], errors="coerce").fillna(0.0)
    return rows


def _round_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)
```

- [ ] **Step 4: Run the focused strategy tests**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_mock_multifactor_signals_create_multiple_long_signals tests/test_kline_backtest_runner.py::test_factor_attribution_summarizes_active_signal_drivers -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/backtest/multifactor_strategy.py tests/test_kline_backtest_runner.py
git commit -m "feat: add mock multifactor signal strategy"
```

---

## Task 4: Wire Mock Strategy Into The K-line Backtest Runner

**Files:**
- Modify: `src/backtest/runner.py`
- Modify: `src/kline/routes.py`
- Test: `tests/test_kline_backtest_runner.py`
- Test: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add failing runner tests for A**

Append to `tests/test_kline_backtest_runner.py`:

```python
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


def test_run_kline_backtest_rejects_mock_strategy_when_not_mock_mode(tmp_path, monkeypatch):
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
```

- [ ] **Step 2: Add failing API test for hidden A metadata**

Append to `tests/test_kline_web_integration.py`:

```python
def test_backtest_api_returns_mock_metadata_without_template_mock_disclosure(
    client, monkeypatch, tmp_path
):
    from src.backtest import runner
    from src.kline import routes

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

    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-03-31",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["mock_metadata"]["data_mode"] == "mock"
    assert body["strategy"]["id"] == "mock_multifactor_demo"

    html = client.get("/kline/MRNA").get_data(as_text=True).lower()
    assert "mock" not in html
    assert "synthetic" not in html
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_run_kline_backtest_uses_mock_multifactor_demo_for_a_tickers tests/test_kline_backtest_runner.py::test_run_kline_backtest_does_not_use_mock_strategy_for_non_a_ticker tests/test_kline_backtest_runner.py::test_run_kline_backtest_rejects_mock_strategy_when_not_mock_mode tests/test_kline_web_integration.py::test_backtest_api_returns_mock_metadata_without_template_mock_disclosure -q
```

Expected:

```text
FAILED ... unexpected keyword argument 'strategy_id'
FAILED ... missing strategy/mock_metadata/factor_attribution
```

- [ ] **Step 4: Modify `runner.py` imports and function signature**

In `src/backtest/runner.py`, add imports:

```python
from src.backtest.mock_dataset import (
    MOCK_DATA_MODE,
    MOCK_SCOPE,
    build_mock_factor_frame,
    is_mock_backtest_ticker,
    mock_run_metadata,
)
from src.backtest.multifactor_strategy import (
    generate_mock_multifactor_signals,
    summarize_factor_attribution,
)
from src.backtest.strategy_registry import (
    EVENT_BASELINE,
    MOCK_MULTIFACTOR_DEMO,
    StrategyAccessError,
    default_strategy_for_kline,
    validate_strategy_access,
)
```

Change `run_kline_backtest()` signature to:

```python
def run_kline_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    report_confidence: float = 1.0,
    strategy_id: str | None = None,
    data_mode: str | None = None,
) -> dict:
```

- [ ] **Step 5: Resolve strategy and guard access in `runner.py`**

After ticker normalization and before loading OHLC, add:

```python
    resolved_strategy_id = strategy_id or default_strategy_for_kline(ticker)
    resolved_data_mode = data_mode or (
        MOCK_DATA_MODE
        if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO and is_mock_backtest_ticker(ticker)
        else "real"
    )
    resolved_mock_scope = (
        MOCK_SCOPE
        if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO and resolved_data_mode == MOCK_DATA_MODE
        else None
    )
    try:
        validate_strategy_access(
            strategy_id=resolved_strategy_id,
            data_mode=resolved_data_mode,
            mock_scope=resolved_mock_scope,
        )
    except StrategyAccessError as exc:
        return {"error": str(exc)}
```

- [ ] **Step 6: Branch signal generation for mock strategy**

Replace the current event-only signal block with:

```python
    mock_metadata = None
    factor_attribution = {}
    if resolved_strategy_id == MOCK_MULTIFACTOR_DEMO:
        factors = build_mock_factor_frame(ticker, price_window)
        signals = generate_mock_multifactor_signals(price_window, factors)
        signal_events = align_events_to_trading_dates(eligible_events, price_window)
        factor_attribution = summarize_factor_attribution(factors)
        mock_metadata = mock_run_metadata(ticker)
    else:
        if eligible_events.empty:
            return {"error": "no trusted backtest-eligible events in date range"}
        signal_events = align_events_to_trading_dates(eligible_events, price_window)
        signals = generate_signals(
            price_window, signal_events, report_confidence=report_confidence
        )
```

Keep `apply_strategy()`, metrics, trades, and result persistence shared for both branches.

- [ ] **Step 7: Add strategy metadata to payload**

In the payload dict, add:

```python
        "strategy": {
            "id": resolved_strategy_id,
            "data_mode": resolved_data_mode,
        },
        "mock_metadata": mock_metadata,
        "factor_attribution": factor_attribution,
```

Keep these keys even when values are `None` or `{}` so frontend/tests have a stable contract.

- [ ] **Step 8: Allow optional strategy in route**

In `src/kline/routes.py`, read optional values before calling `run_kline_backtest()`:

```python
        raw_strategy_id = data.get("strategy_id")
        strategy_id = str(raw_strategy_id).strip() if raw_strategy_id else None
        raw_data_mode = data.get("data_mode")
        data_mode = str(raw_data_mode).strip() if raw_data_mode else None
```

Pass them into `run_kline_backtest()`:

```python
            strategy_id=strategy_id,
            data_mode=data_mode,
```

- [ ] **Step 9: Run focused tests**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_run_kline_backtest_uses_mock_multifactor_demo_for_a_tickers tests/test_kline_backtest_runner.py::test_run_kline_backtest_does_not_use_mock_strategy_for_non_a_ticker tests/test_kline_backtest_runner.py::test_run_kline_backtest_rejects_mock_strategy_when_not_mock_mode tests/test_kline_web_integration.py::test_backtest_api_returns_mock_metadata_without_template_mock_disclosure -q
```

Expected:

```text
4 passed
```

- [ ] **Step 10: Commit Task 4**

Run:

```powershell
git add src/backtest/runner.py src/kline/routes.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py
git commit -m "feat: wire mock multifactor kline backtest"
```

---

## Task 5: Render Factor Attribution Without Mock Disclosure

**Files:**
- Modify: `static/kline/workspace.js`
- Test: `tests/test_kline_workspace_js.py`

- [ ] **Step 1: Add failing frontend tests**

Append to `tests/test_kline_workspace_js.py`:

```python
def test_workspace_js_backtest_renders_factor_attribution_without_mock_disclosure():
    script = r"""
    const fs = require('fs');
    const vm = require('vm');
    const workspaceJs = fs.readFileSync('static/kline/workspace.js', 'utf8');

    class Element {
      constructor(tag) {
        this.tagName = tag;
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.textContent = '';
        this.hidden = false;
        this.className = '';
        this.listeners = {};
        this.elements = {};
      }
      appendChild(child) { this.children.push(child); return child; }
      replaceChildren(...children) { this.children = children; }
      setAttribute(name, value) { this.attributes[name] = value; }
      addEventListener(type, fn) { this.listeners[type] = fn; }
      querySelector() { return null; }
      get innerText() {
        return [this.textContent].concat(this.children.map((child) => child.innerText || child.textContent || '')).join(' ');
      }
    }

    const panel = new Element('section');
    const document = {
      createElement: (tag) => new Element(tag),
      createTextNode: (text) => ({ textContent: text, innerText: text }),
      querySelector: (selector) => selector === '[data-panel="backtest"]' ? panel : null,
      getElementById: () => null,
      addEventListener: (type, fn) => { if (type === 'DOMContentLoaded') fn(); }
    };
    const window = {
      __KLINE_WORKSPACE__: {
        ticker: 'MRNA',
        price: { date_range: { start: '2025-01-02', end: '2025-03-31' } },
        layers: [{ kind: 'backtest', summary: {
          run_id: 'run-1',
          metrics: { sharpe: 1.2 },
          factor_attribution: {
            active_factor_days: 8,
            mean_mock_score: 0.61,
            mean_event_factor: 0.32,
            mean_liquidity_factor: 0.12
          },
          mock_metadata: {
            data_mode: 'mock',
            synthetic: true,
            positive_demo_expected: true
          }
        }}]
      }
    };
    const context = { window, document, console, fetch: () => Promise.reject(new Error('unused')) };
    vm.createContext(context);
    vm.runInContext(workspaceJs, context);

    const text = panel.innerText.toLowerCase();
    if (!text.includes('factor_attribution')) throw new Error(text);
    if (!text.includes('active_factor_days')) throw new Error(text);
    if (text.includes('mock')) throw new Error(text);
    if (text.includes('synthetic')) throw new Error(text);
    if (text.includes('positive_demo_expected')) throw new Error(text);
    """
    run_node_script(script)
```

- [ ] **Step 2: Run the frontend test and verify it fails**

Run:

```powershell
pytest tests/test_kline_workspace_js.py::test_workspace_js_backtest_renders_factor_attribution_without_mock_disclosure -q
```

Expected:

```text
FAILED ... factor_attribution
```

- [ ] **Step 3: Render factor attribution**

In `static/kline/workspace.js`, update `renderBacktestDiagnostics()`:

```javascript
  function renderBacktestDiagnostics(node, body) {
    ["event_filter", "signal_summary", "baseline", "factor_attribution"].forEach(function (key) {
      if (!body || !body[key]) {
        return;
      }
      var section = makeElement("section", { className: "backtest-diagnostics" });
      section.appendChild(makeElement("h3", { className: "panel-heading", text: key }));
      appendMetrics(section, body[key]);
      node.appendChild(section);
    });
    renderEventAttribution(node, body && body.event_attribution);
  }
```

Do not add rendering for `mock_metadata`, `strategy.data_mode`, or `positive_demo_expected`.

- [ ] **Step 4: Run the frontend test**

Run:

```powershell
pytest tests/test_kline_workspace_js.py::test_workspace_js_backtest_renders_factor_attribution_without_mock_disclosure -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add static/kline/workspace.js tests/test_kline_workspace_js.py
git commit -m "feat: show factor attribution in kline backtest"
```

---

## Task 6: Verify All Four A Tickers End-To-End

**Files:**
- Modify: `tests/test_kline_backtest_runner.py`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add an end-to-end runner test for the four mock tickers**

Append to `tests/test_kline_backtest_runner.py`:

```python
def test_mock_a_backtest_positive_for_all_four_demo_tickers(tmp_path, monkeypatch):
    from src.backtest import runner

    def ohlc_for(ticker):
        base = {"MRNA": 100.0, "JNJ": 150.0, "LLY": 700.0, "ABBA": 20.0}[ticker]
        rows = []
        price = base
        for index in range(55):
            date = pd.Timestamp("2025-01-02") + pd.offsets.BDay(index)
            open_price = price
            close_price = open_price + (2.5 if index % 5 in {1, 2, 3} else -0.4)
            rows.append(
                {
                    "date": date,
                    "open": open_price,
                    "high": max(open_price, close_price) + 1.0,
                    "low": min(open_price, close_price) - 1.0,
                    "close": close_price,
                    "volume": 1_000_000 + index * 15_000,
                }
            )
            price = close_price
        return pd.DataFrame(rows)

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", ohlc_for)
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

    for ticker in ["MRNA", "JNJ", "LLY", "ABBA"]:
        payload = runner.run_kline_backtest(
            ticker=ticker,
            start_date="2025-01-02",
            end_date="2025-03-31",
        )
        assert payload["strategy"]["id"] == "mock_multifactor_demo"
        assert payload["mock_metadata"]["ticker"] == ticker
        assert payload["signal_summary"]["active_signal_days"] >= 6
        assert len(payload["trades"]) >= 5
        assert payload["baseline"]["strategy_return"] > 0
```

- [ ] **Step 2: Run the end-to-end runner test**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py::test_mock_a_backtest_positive_for_all_four_demo_tickers -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Add route regression test for explicit non-mock rejection**

Append to `tests/test_kline_web_integration.py`:

```python
def test_backtest_api_rejects_mock_strategy_in_real_mode(client):
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "MRNA",
            "start_date": "2025-01-02",
            "end_date": "2025-01-08",
            "strategy_id": "mock_multifactor_demo",
            "data_mode": "real",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "mock_multifactor_demo requires data_mode='mock'"
    }
```

- [ ] **Step 4: Run the route regression test**

Run:

```powershell
pytest tests/test_kline_web_integration.py::test_backtest_api_rejects_mock_strategy_in_real_mode -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Run the full affected test suite**

Run:

```powershell
pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_backtest_runner.py tests/test_kline_backtest_trusted_inputs.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_workspace_service.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 6: Manually verify local cached four-ticker output**

Run:

```powershell
@'
from src.backtest.runner import run_kline_backtest
for ticker in ["MRNA", "JNJ", "LLY", "ABBA"]:
    payload = run_kline_backtest(ticker, "2025-01-01", "2026-05-06")
    print(ticker, payload.get("strategy", {}).get("id"), payload.get("signal_summary", {}).get("active_signal_days"), len(payload.get("trades", [])), payload.get("baseline", {}).get("strategy_return"))
'@ | python -
```

Expected:

```text
MRNA mock_multifactor_demo <active count >= 6> <trade count >= 5> <positive number>
JNJ mock_multifactor_demo <active count >= 6> <trade count >= 5> <positive number>
LLY mock_multifactor_demo <active count >= 6> <trade count >= 5> <positive number>
ABBA mock_multifactor_demo <active count >= 6> <trade count >= 5> <positive number>
```

- [ ] **Step 7: Commit Task 6**

Run:

```powershell
git add tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py
git commit -m "test: cover four ticker mock backtest demo"
```

---

## Task 7: Final Verification

**Files:**
- No code changes unless verification reveals a failure.

- [ ] **Step 1: Run the full relevant Python suite**

Run:

```powershell
pytest tests/test_backtest_data_loader.py tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_backtest_runner.py tests/test_kline_backtest_trusted_inputs.py tests/test_kline_static_bundle.py tests/test_market_data_service.py tests/test_event_ingestion_service.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run the K-line frontend build**

Run:

```powershell
npm run build
```

Working directory:

```text
F:\Visual Studio Code\alpha\Cassandra\src\kline
```

Expected:

```text
✓ built
```

- [ ] **Step 3: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected:

```text
Only files from this plan are changed, plus pre-existing dirty files remain untouched.
```

- [ ] **Step 4: Final commit if Tasks 1-6 were not committed separately**

If tasks were not committed individually, run:

```powershell
git add src/backtest/mock_dataset.py src/backtest/strategy_registry.py src/backtest/multifactor_strategy.py src/backtest/runner.py src/kline/routes.py static/kline/workspace.js tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py tests/test_kline_workspace_js.py
git commit -m "feat: add mock multifactor kline backtest demo"
```

Expected:

```text
commit created
```

---

## Self-Review Notes

- Spec coverage:
  - A mock universe is covered by Tasks 1 and 6.
  - Backend mock metadata is covered by Tasks 1 and 4.
  - Multi-factor A strategy is covered by Tasks 3 and 4.
  - Positive equity for mock A is covered by Tasks 4 and 6.
  - UI non-disclosure is covered by Tasks 4 and 5.
  - B/C guardrails are covered by Task 2 and Task 6.

- Deliberate deferrals:
  - DuckDB/Parquet snapshot layer belongs in a separate B data-foundation plan.
  - Backtest Lab UI belongs in a separate B UI plan.
  - ML feature matrix and walk-forward model belong in a separate C plan.
