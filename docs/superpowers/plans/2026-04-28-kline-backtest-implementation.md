# KLine Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chart-ready KLine backtest response with metrics, equity curve, event CAR, signal overlays, and trade overlays.

**Architecture:** Keep the backtest backend deterministic. `run_kline_backtest()` loads OHLC and stored events, generates daily signals, applies the strategy, serializes metrics, equity curve, CAR, signals, and derived trade spans. The frontend consumes the response and overlays equity, signals, and trades on the existing chart.

**Tech Stack:** Python 3.11, pandas, pytest, Flask, TypeScript, React, D3, Vite.

---

## File Structure

- `src/backtest/runner.py`: serialize signals and trades into the backtest result payload.
- `src/backtest/strategy.py`: keep deterministic strategy execution; no Gemini.
- `app.py`: keep `/api/backtest/run` validation and return the expanded payload.
- `src/kline/chart/types.ts`: add signal and trade overlay contracts.
- `src/kline/chart/CandlestickChart.tsx`: render signal and trade markers.
- `src/kline/chart/index.tsx`: pass overlay props into the chart.
- `templates/kline_report.html`: store overlay arrays and pass them into the chart.
- `tests/test_kline_backtest_runner.py`: new focused backend tests.
- `tests/test_kline_web_integration.py`: API route and template contract tests.

---

### Task 1: Add Backend Tests For Signal And Trade Payloads

**Files:**
- Create: `tests/test_kline_backtest_runner.py`
- Modify: `src/backtest/runner.py`

- [ ] **Step 1: Write failing backend tests**

Create `tests/test_kline_backtest_runner.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _ohlc() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-04-20", "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0, "volume": 1000},
            {"date": "2026-04-21", "open": 103.0, "high": 108.0, "low": 102.0, "close": 107.0, "volume": 1400},
            {"date": "2026-04-22", "open": 107.0, "high": 109.0, "low": 104.0, "close": 105.0, "volume": 1200},
            {"date": "2026-04-23", "open": 105.0, "high": 111.0, "low": 104.0, "close": 110.0, "volume": 1600},
        ]
    )


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": "evt_positive",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": "BIIB",
                "disease_area": "Alzheimer Disease",
                "catalyst": "Positive Phase 3 readout",
                "sentiment": "positive",
                "price_impact": 0.05,
                "source": "clinicaltrials",
            },
            {
                "id": "evt_negative",
                "date": "2026-04-22",
                "type": "regulatory_change",
                "priority": 1,
                "ticker": "BIIB",
                "disease_area": "Alzheimer Disease",
                "catalyst": "Regulatory risk update",
                "sentiment": "negative",
                "price_impact": -0.03,
                "source": "openfda",
            },
        ]
    )


def test_run_kline_backtest_returns_chart_ready_signals_and_trades(monkeypatch, tmp_path):
    from src.backtest import runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: _ohlc())
    monkeypatch.setattr(runner, "get_events", lambda ticker, start_date=None, end_date=None: _events())

    payload = runner.run_kline_backtest(
        ticker="BIIB",
        start_date="2026-04-20",
        end_date="2026-04-23",
        report_confidence=1.0,
    )

    assert payload["ticker"] == "BIIB"
    assert payload["metrics"]
    assert payload["equity_curve"] == [
        {"date": "2026-04-20", "equity": 1.0},
        {"date": "2026-04-21", "equity": payload["equity_curve"][1]["equity"]},
        {"date": "2026-04-22", "equity": payload["equity_curve"][2]["equity"]},
        {"date": "2026-04-23", "equity": payload["equity_curve"][3]["equity"]},
    ]
    assert payload["signals"][0]["date"] == "2026-04-20"
    assert payload["signals"][0]["signal"] == 1
    assert payload["signals"][0]["source_event_ids"] == ["evt_positive"]
    assert payload["signals"][1]["date"] == "2026-04-21"
    assert payload["signals"][2]["date"] == "2026-04-22"
    assert payload["signals"][2]["signal"] == -1
    assert payload["signals"][2]["source_event_ids"] == ["evt_negative"]
    assert all({"entry_date", "exit_date", "direction", "size", "entry_price", "exit_price", "pnl_pct"}.issubset(trade) for trade in payload["trades"])
    assert Path(tmp_path / f"{payload['run_id']}.json").exists()


def test_serialize_signals_keeps_empty_event_days():
    from src.backtest.runner import _serialize_signals

    signals = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-20"), "signal": 1, "signal_strength": 0.9},
            {"date": pd.Timestamp("2026-04-21"), "signal": 0, "signal_strength": 0.0},
        ]
    )
    events = pd.DataFrame(
        [
            {"id": "evt_1", "date": "2026-04-20"},
        ]
    )

    rows = _serialize_signals(signals, events)

    assert rows == [
        {"date": "2026-04-20", "signal": 1, "signal_strength": 0.9, "source_event_ids": ["evt_1"]},
        {"date": "2026-04-21", "signal": 0, "signal_strength": 0.0, "source_event_ids": []},
    ]
```

- [ ] **Step 2: Run tests and verify expected failure**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
FAILED tests/test_kline_backtest_runner.py::test_run_kline_backtest_returns_chart_ready_signals_and_trades
FAILED tests/test_kline_backtest_runner.py::test_serialize_signals_keeps_empty_event_days
```

The failure should mention missing `_serialize_signals` or missing `signals` / `trades` keys.

- [ ] **Step 3: Implement signal and trade serialization**

In `src/backtest/runner.py`, add these helpers above `run_kline_backtest()`:

```python
def _event_ids_by_date(events: pd.DataFrame) -> dict[str, list[str]]:
    if events.empty or "date" not in events.columns:
        return {}

    event_rows = events.copy()
    event_rows["date"] = pd.to_datetime(event_rows["date"]).dt.strftime("%Y-%m-%d")
    if "id" not in event_rows.columns:
        event_rows["id"] = ""

    grouped: dict[str, list[str]] = {}
    for row in event_rows.itertuples(index=False):
        event_id = str(getattr(row, "id", "") or "").strip()
        if not event_id:
            continue
        date_key = str(getattr(row, "date"))
        grouped.setdefault(date_key, []).append(event_id)
    return grouped


def _serialize_signals(signals: pd.DataFrame, events: pd.DataFrame) -> list[dict]:
    event_ids = _event_ids_by_date(events)
    rows: list[dict] = []
    if signals.empty:
        return rows

    for row in signals.itertuples(index=False):
        date_key = _to_iso_date(getattr(row, "date"))
        rows.append(
            {
                "date": date_key,
                "signal": int(getattr(row, "signal", 0)),
                "signal_strength": float(getattr(row, "signal_strength", 0.0)),
                "source_event_ids": event_ids.get(date_key, []),
            }
        )
    return rows


def _derive_trades(price_window: pd.DataFrame, results: pd.DataFrame) -> list[dict]:
    if price_window.empty or results.empty:
        return []

    prices = price_window.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    merged = results.copy()
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged.merge(prices[["date", "open", "close"]], on="date", how="left")

    trades: list[dict] = []
    active: dict | None = None
    previous_position = 0.0

    for row in merged.itertuples(index=False):
        position = float(getattr(row, "position", 0.0) or 0.0)
        date_key = _to_iso_date(getattr(row, "date"))
        open_price = float(getattr(row, "open", 0.0) or 0.0)
        close_price = float(getattr(row, "close", 0.0) or 0.0)

        if active is None and position != 0:
            active = {
                "entry_date": date_key,
                "direction": "long" if position > 0 else "short",
                "size": abs(position),
                "entry_price": open_price,
            }

        if active is not None and previous_position != 0 and position == 0:
            active["exit_date"] = date_key
            active["exit_price"] = close_price
            active["pnl_pct"] = _trade_pnl_pct(active["direction"], active["entry_price"], close_price)
            trades.append(active)
            active = None

        if active is not None and previous_position != 0 and position != 0 and (position > 0) != (previous_position > 0):
            active["exit_date"] = date_key
            active["exit_price"] = close_price
            active["pnl_pct"] = _trade_pnl_pct(active["direction"], active["entry_price"], close_price)
            trades.append(active)
            active = {
                "entry_date": date_key,
                "direction": "long" if position > 0 else "short",
                "size": abs(position),
                "entry_price": open_price,
            }

        previous_position = position

    if active is not None:
        last = merged.iloc[-1]
        exit_price = float(last["close"])
        active["exit_date"] = _to_iso_date(last["date"])
        active["exit_price"] = exit_price
        active["pnl_pct"] = _trade_pnl_pct(active["direction"], active["entry_price"], exit_price)
        trades.append(active)

    return trades


def _trade_pnl_pct(direction: str, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    raw = exit_price / entry_price - 1.0
    return round(raw if direction == "long" else -raw, 6)
```

In `run_kline_backtest()`, add the serialized fields to `payload`:

```python
    signal_rows = _serialize_signals(signals, events)
    trade_rows = _derive_trades(price_window, results)

    payload = {
        "run_id": run_id,
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "metrics": metrics,
        "equity_curve": equity_curve,
        "event_car": event_car,
        "signals": signal_rows,
        "trades": trade_rows,
    }
```

- [ ] **Step 4: Run focused backend tests**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add src/backtest/runner.py tests/test_kline_backtest_runner.py
git commit -m "feat: add chart ready backtest overlays"
```

Expected:

```text
[branch commit] feat: add chart ready backtest overlays
```

---

### Task 2: Add API Contract Test For Expanded Backtest Payload

**Files:**
- Modify: `tests/test_kline_web_integration.py`
- Modify: `app.py`

- [ ] **Step 1: Add failing API route test**

Append to `tests/test_kline_web_integration.py`:

```python
def test_backtest_api_returns_signal_and_trade_overlays(monkeypatch):
    def fake_run_kline_backtest(**kwargs):
        return {
            "run_id": "run_001",
            "ticker": kwargs["ticker"],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "metrics": {"sharpe": 1.2},
            "equity_curve": [{"date": kwargs["start_date"], "equity": 1.0}],
            "event_car": [],
            "signals": [{"date": kwargs["start_date"], "signal": 1, "signal_strength": 0.5, "source_event_ids": ["evt_1"]}],
            "trades": [{"entry_date": kwargs["start_date"], "exit_date": kwargs["end_date"], "direction": "long", "size": 0.1, "entry_price": 10.0, "exit_price": 11.0, "pnl_pct": 0.1}],
        }

    monkeypatch.setattr(app_module, "run_kline_backtest", fake_run_kline_backtest)

    client = app.test_client()
    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "BIIB",
            "start_date": "2026-04-20",
            "end_date": "2026-04-23",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["signals"][0]["source_event_ids"] == ["evt_1"]
    assert body["trades"][0]["direction"] == "long"
```

- [ ] **Step 2: Run API test**

Run:

```powershell
pytest tests/test_kline_web_integration.py::test_backtest_api_returns_signal_and_trade_overlays -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
1 passed
```

If it fails because `app.py` filters the response, update `api_backtest_run()` to return `jsonify(result)` unchanged after error handling.

- [ ] **Step 3: Commit if app or tests changed**

Run:

```powershell
git status --short
git add tests/test_kline_web_integration.py app.py
git commit -m "test: cover backtest overlay api payload"
```

Expected:

```text
[branch commit] test: cover backtest overlay api payload
```

If only the test changed, stage only the test file.

---

### Task 3: Add Frontend Overlay Types And Prop Wiring

**Files:**
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/index.tsx`
- Modify: `src/kline/chart/CandlestickChart.tsx`

- [ ] **Step 1: Extend chart types**

In `src/kline/chart/types.ts`, add:

```typescript
export interface SignalMarker {
  date: string;
  signal: -1 | 0 | 1;
  signal_strength: number;
  source_event_ids?: string[];
}

export interface TradeMarker {
  entry_date: string;
  exit_date: string;
  direction: 'long' | 'short';
  size: number;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
}
```

Update `ChartConfig`:

```typescript
export interface ChartConfig {
  ohlcData: OHLCRow[];
  events: BiotechEvent[];
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
  highlightedEventId?: string;
  equityCurve?: EquityPoint[];
  signals?: SignalMarker[];
  trades?: TradeMarker[];
}
```

- [ ] **Step 2: Wire props through index**

In `src/kline/chart/index.tsx`, update the type export:

```typescript
export type { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, EquityPoint, SignalMarker, TradeMarker, ChartConfig } from './types';
```

Pass props to `CandlestickChart`:

```tsx
      equityCurve={config.equityCurve}
      signals={config.signals}
      trades={config.trades}
```

- [ ] **Step 3: Add props to CandlestickChart**

In `src/kline/chart/CandlestickChart.tsx`, update the import:

```typescript
import { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, SignalMarker, TradeMarker } from './types';
```

Update `Props`:

```typescript
interface Props {
  ohlcData: OHLCRow[];
  events?: BiotechEvent[] | null;
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
  highlightedEventId?: string;
  equityCurve?: Array<{ date: string; equity: number }>;
  signals?: SignalMarker[];
  trades?: TradeMarker[];
}
```

Add to destructuring:

```typescript
  signals,
  trades,
```

Update the redraw dependency:

```typescript
  }, [ohlcData, events, highlightedEventId, equityCurve, signals, trades]);
```

- [ ] **Step 4: Run TypeScript build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add src/kline/chart/types.ts src/kline/chart/index.tsx src/kline/chart/CandlestickChart.tsx static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css static/vendor/pokie-chart-loader.js
git commit -m "feat: wire kline backtest overlay props"
```

Expected:

```text
[branch commit] feat: wire kline backtest overlay props
```

---

### Task 4: Render Signal And Trade Overlays

**Files:**
- Modify: `src/kline/chart/CandlestickChart.tsx`

- [ ] **Step 1: Add overlay drawing helpers**

In `src/kline/chart/CandlestickChart.tsx`, add this inside `drawChart()` after candlesticks are drawn and before event placement:

```typescript
    // Signal markers from backtest output
    if (signals && signals.length > 0) {
      const signalLayer = g.append('g').attr('class', 'signal-layer');
      signals.forEach((signalItem) => {
        if (signalItem.signal === 0) return;
        const ohlc = dateToOhlc.get(signalItem.date);
        if (!ohlc) return;

        const cx = x(ohlc.date);
        const isLong = signalItem.signal > 0;
        const cy = isLong ? y(ohlc.low) + 16 : y(ohlc.high) - 16;
        const color = isLong ? '#22c55e' : '#ef4444';
        const points = isLong
          ? `${cx},${cy - 7} ${cx - 6},${cy + 5} ${cx + 6},${cy + 5}`
          : `${cx},${cy + 7} ${cx - 6},${cy - 5} ${cx + 6},${cy - 5}`;

        signalLayer.append('polygon')
          .attr('points', points)
          .attr('fill', color)
          .attr('stroke', '#0f172a')
          .attr('stroke-width', 1.2)
          .attr('opacity', Math.max(0.45, Math.min(1, signalItem.signal_strength || 0.45)));
      });
    }

    // Trade spans from backtest output
    if (trades && trades.length > 0) {
      const tradeLayer = g.insert('g', ':first-child').attr('class', 'trade-layer');
      trades.forEach((trade) => {
        const entry = dateToOhlc.get(trade.entry_date);
        const exit = dateToOhlc.get(trade.exit_date);
        if (!entry || !exit) return;
        const x0 = x(entry.date);
        const x1 = x(exit.date);
        const left = Math.min(x0, x1);
        const widthSpan = Math.max(2, Math.abs(x1 - x0));
        const color = trade.pnl_pct >= 0 ? '#22c55e' : '#ef4444';

        tradeLayer.append('rect')
          .attr('x', left)
          .attr('y', 0)
          .attr('width', widthSpan)
          .attr('height', height)
          .attr('fill', color)
          .attr('opacity', 0.055);
      });
    }
```

- [ ] **Step 2: Run TypeScript build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 3: Commit**

Run:

```powershell
git status --short
git add src/kline/chart/CandlestickChart.tsx static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css static/vendor/pokie-chart-loader.js
git commit -m "feat: render kline backtest overlays"
```

Expected:

```text
[branch commit] feat: render kline backtest overlays
```

---

### Task 5: Pass Backtest Overlays From Template To Chart

**Files:**
- Modify: `templates/kline_report.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add failing template contract test**

Append to `tests/test_kline_web_integration.py`:

```python
def test_kline_template_passes_backtest_overlays_to_chart(monkeypatch):
    monkeypatch.setattr(app_module, "get_ohlc_rows", lambda ticker, max_age_hours=24: [])
    monkeypatch.setattr(app_module, "get_events_for_ticker", lambda ticker, max_age_hours=6: [])

    client = app.test_client()
    response = client.get("/kline/BIIB")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "pageState.signals" in html
    assert "pageState.trades" in html
    assert "signals: pageState.signals" in html
    assert "trades: pageState.trades" in html
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
pytest tests/test_kline_web_integration.py::test_kline_template_passes_backtest_overlays_to_chart -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
FAILED tests/test_kline_web_integration.py::test_kline_template_passes_backtest_overlays_to_chart
```

- [ ] **Step 3: Update browser state and chart config**

In `templates/kline_report.html`, add to `pageState`:

```javascript
    equityCurve: [],
    signals: [],
    trades: [],
```

Update chart render config:

```javascript
        equityCurve: pageState.equityCurve,
        signals: pageState.signals,
        trades: pageState.trades,
```

In `hydrateBacktestRun()` after setting `equityCurve`, add:

```javascript
      pageState.signals = Array.isArray(payload.signals) ? payload.signals : [];
      pageState.trades = Array.isArray(payload.trades) ? payload.trades : [];
```

In `handleBacktestSubmit()` after setting `equityCurve`, add:

```javascript
      pageState.signals = Array.isArray(body.signals) ? body.signals : [];
      pageState.trades = Array.isArray(body.trades) ? body.trades : [];
```

- [ ] **Step 4: Run focused template tests**

Run:

```powershell
pytest tests/test_kline_web_integration.py -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
All tests in tests/test_kline_web_integration.py pass.
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add templates/kline_report.html tests/test_kline_web_integration.py
git commit -m "feat: pass backtest overlays to kline chart"
```

Expected:

```text
[branch commit] feat: pass backtest overlays to kline chart
```

---

### Task 6: Verify Backtest End To End

**Files:**
- No source files.

- [ ] **Step 1: Run backend tests**

Run:

```powershell
pytest tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py -q --basetemp .pytest_tmp_kline_backtest
```

Expected:

```text
Command exits with code 0 and the pytest summary contains only passed tests for:
tests/test_kline_backtest_runner.py
tests/test_kline_web_integration.py
```

- [ ] **Step 2: Run TypeScript build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected:

```text
No output.
```

- [ ] **Step 4: Remove temporary pytest directory**

Run:

```powershell
$repo = (Resolve-Path -LiteralPath '.').Path
$target = (Resolve-Path -LiteralPath '.pytest_tmp_kline_backtest' -ErrorAction SilentlyContinue)
if ($target) {
  if (-not $target.Path.StartsWith($repo)) { throw "Refusing to remove path outside repository root: $($target.Path)" }
  Remove-Item -LiteralPath $target.Path -Recurse -Force
}
```

Expected:

```text
No output.
```

- [ ] **Step 5: Confirm clean scoped status**

Run:

```powershell
git status --short src/backtest src/kline templates/kline_report.html tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py app.py
```

Expected:

```text
No uncommitted files from this plan.
```
