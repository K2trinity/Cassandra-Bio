# Biotech Universe Backtest Data UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four-ticker mock-oriented K-line backtest workflow with a real `biotech_us_v1` backtest UI and local data foundation that handles survivorship-bias warnings and provider rate limits.

**Architecture:** Implement this in small commits. First remove production mock-universe entrypoints and add chart display modes. Then add provider-neutral universe/data ingestion contracts, rate-limit/fetch-log infrastructure, Tiingo OHLCV normalization, FMP/SEC fundamental normalization, and finally wire portfolio backtests to database-backed universe membership with data credibility metrics.

**Tech Stack:** Flask routes, vanilla workspace JavaScript, React/D3 chart bundle under `src/kline`, DuckDB catalog tables, Parquet data partitions, SQLite event store, pytest, Node/Vite chart build.

---

## Scope And Execution Rules

- Execute tasks in order.
- Keep A mock internals only where existing tests require the historical isolated demo path; remove the production UI and production route exposure for mock universe runs.
- Do not make live HTTP calls in tests. All provider tests use fixtures or fake clients.
- Do not put API keys in source, tests, docs, or committed data.
- Do not silently fall back from Tiingo to yfinance for formal snapshots.
- Use repo-local pytest temp dirs on Windows with task-specific names, for
  example `--basetemp .pytest_tmp\biotech-task1`.
- After each task, commit only the files touched by that task.

## File Structure

Modify:

- `static/kline/workspace.js`: remove demo universe button, add chart display mode state, send `universe_id` and `data_snapshot_id` in portfolio requests.
- `static/kline/workspace.css`: make Backtest panel controls readable in dark mode, including selects and status chips.
- `src/kline/chart/types.ts`: add `ChartDisplayMode`.
- `src/kline/chart/index.tsx`: pass `displayMode` into the chart component.
- `src/kline/chart/CandlestickChart.tsx`: hide candles/events/backtest overlays according to display mode.
- `src/kline/routes.py`: remove or deprecate production demo route and accept real universe request fields.
- `src/backtest/portfolio_runner.py`: replace hard-coded four-ticker real universe with database-backed universe loading.
- `src/backtest/research_db.py`: add universe snapshot, provider fetch log, and fundamentals catalog tables.
- `src/backtest/data_sources.py`: add Tiingo, FMP, SEC, and current-constituents-only source policies.
- `src/backtest/price_snapshot.py`: support Tiingo adjusted OHLCV normalization without faking adjusted fields.
- `scripts/bootstrap_research_snapshot.py`: accept real universe and source options.

Create:

- `src/backtest/universe.py`: DuckDB-backed universe membership loader and eligibility summaries.
- `src/backtest/universe_builder.py`: provider-neutral universe normalization and current-constituents-only bias metadata.
- `src/data_ingestion/__init__.py`: ingestion package marker.
- `src/data_ingestion/rate_limit.py`: deterministic provider rate-limit policy helpers.
- `src/data_ingestion/provider_log.py`: DuckDB fetch-log writer.
- `src/data_ingestion/tiingo_prices.py`: Tiingo EOD fixture/API response normalization.
- `src/data_ingestion/fundamentals.py`: FMP and SEC normalized fundamental payload helpers.
- `scripts/build_biotech_universe_snapshot.py`: CLI for local universe snapshot construction from source files.

Modify tests:

- `tests/test_kline_workspace_js.py`
- `tests/test_kline_web_integration.py`
- `tests/test_kline_static_bundle.py`
- `tests/test_kline_backtest_runner.py`
- `tests/test_backtest_data_sources.py`
- `tests/test_backtest_price_snapshot.py`
- `tests/test_bootstrap_research_snapshot.py`

Create tests:

- `tests/test_biotech_universe_builder.py`
- `tests/test_biotech_universe_loader.py`
- `tests/test_provider_rate_limit.py`
- `tests/test_provider_fetch_log.py`
- `tests/test_tiingo_price_ingestion.py`
- `tests/test_fundamentals_ingestion.py`

---

### Task 1: Remove Production Demo Universe Entrypoints

**Files:**

- Modify: `static/kline/workspace.js`
- Modify: `src/kline/routes.py`
- Modify: `tests/test_kline_workspace_js.py`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Update workspace JS tests to require no demo button**

Replace `test_workspace_js_backtest_panel_renders_single_and_universe_buttons` in `tests/test_kline_workspace_js.py` with:

```python
def test_workspace_js_backtest_panel_renders_single_and_universe_buttons_without_demo():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        const buttonText = form.children
          .filter((child) => child.tagName === 'BUTTON')
          .map((button) => button.textContent);

        if (!buttonText.includes('Run Backtest')) {
          throw new Error('single-ticker backtest button missing: ' + buttonText.join(','));
        }
        if (!buttonText.includes('Run Universe')) {
          throw new Error('universe backtest button missing: ' + buttonText.join(','));
        }
        if (buttonText.includes('Run Demo Universe')) {
          throw new Error('demo universe button must not render: ' + buttonText.join(','));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout
```

Delete `test_workspace_js_demo_universe_button_uses_explicit_demo_endpoint` entirely.

- [ ] **Step 2: Add route test proving demo endpoint is gone**

In `tests/test_kline_web_integration.py`, replace the two demo route tests that patch `run_mock_biotech_portfolio_backtest` with this test:

```python
def test_demo_portfolio_endpoint_is_not_available(client):
    response = client.post(
        "/api/backtest/portfolio/demo/run",
        json={
            "ticker": "MRNA",
            "start_date": "2026-04-20",
            "end_date": "2026-04-21",
            "stop_loss_pct": -0.08,
            "max_position_pct": 0.2,
            "slippage_pct": 0.001,
            "holding_period_days": 5,
        },
    )

    assert response.status_code == 404
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_kline_workspace_js.py::test_workspace_js_backtest_panel_renders_single_and_universe_buttons_without_demo tests/test_kline_web_integration.py::test_demo_portfolio_endpoint_is_not_available -q --basetemp .pytest_tmp\biotech-task1-fail
```

Expected: FAIL because `Run Demo Universe` and `/api/backtest/portfolio/demo/run` still exist.

- [ ] **Step 4: Remove demo UI wiring**

In `static/kline/workspace.js`, remove this block from `renderBacktest`:

```javascript
    var demoUniverseButton = makeElement("button", {
      type: "button",
      className: "backtest-universe-button",
      text: "Run Demo Universe"
    });
```

Remove this append:

```javascript
    form.appendChild(demoUniverseButton);
```

Remove this click handler:

```javascript
    demoUniverseButton.addEventListener("click", function (event) {
      event.preventDefault();
      runBacktest("/api/backtest/portfolio/demo/run", {
        portfolio: true,
        runningText: "Running demo universe backtest."
      });
    });
```

- [ ] **Step 5: Remove production demo route import and route**

In `src/kline/routes.py`, change the portfolio import from:

```python
from src.backtest.portfolio_runner import (
    BIOTECH_MOCK_TICKERS,
    BIOTECH_REAL_TICKERS,
    DISCLOSURE_KEYS,
    run_mock_biotech_portfolio_backtest,
    run_real_biotech_portfolio_backtest,
)
```

to:

```python
from src.backtest.portfolio_runner import (
    BIOTECH_REAL_TICKERS,
    DISCLOSURE_KEYS,
    run_real_biotech_portfolio_backtest,
)
```

Delete the complete `api_backtest_portfolio_demo_run()` route function.

- [ ] **Step 6: Run task tests**

Run:

```powershell
pytest tests/test_kline_workspace_js.py tests/test_kline_web_integration.py -q --basetemp .pytest_tmp\biotech-task1
```

Expected: PASS after updating any assertions that specifically expected the demo route or demo button.

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add static\kline\workspace.js src\kline\routes.py tests\test_kline_workspace_js.py tests\test_kline_web_integration.py
git commit -m "fix: remove demo universe backtest entrypoint"
```

---

### Task 2: Add Workspace Chart Display Mode Controls

**Files:**

- Modify: `static/kline/workspace.js`
- Modify: `static/kline/workspace.css`
- Modify: `tests/test_kline_workspace_js.py`

- [ ] **Step 1: Add failing workspace JS tests for chart modes**

Add these tests to `tests/test_kline_workspace_js.py`:

```python
def test_workspace_js_backtest_panel_has_chart_mode_control():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace());
        runWorkspace();

        const mode = document.querySelector('[name="chart_display_mode"]');
        if (!mode) {
          throw new Error('chart display mode select missing');
        }
        const values = mode.children.map((child) => child.value);
        ['candles_with_backtest', 'backtest_only', 'candles_only'].forEach((expected) => {
          if (!values.includes(expected)) {
            throw new Error('chart display mode missing ' + expected + ': ' + values.join(','));
          }
        });
        if (mode.value !== 'candles_with_backtest') {
          throw new Error('unexpected default chart mode: ' + mode.value);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_only_mode_passes_display_mode_and_hides_events():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{ id: 'evt-1', ticker: 'MRNA', date: '2026-04-20', type: 'news', priority: 1, sentiment: 'positive' }]
          }, {
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: false,
            series: []
          }]
        }));
        runWorkspace();

        const mode = document.querySelector('[name="chart_display_mode"]');
        mode.value = 'backtest_only';
        mode.dispatchEvent({ type: 'change' });

        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.displayMode !== 'backtest_only') {
          throw new Error('chart did not receive backtest_only mode: ' + latestConfig.displayMode);
        }
        if (latestConfig.events && latestConfig.events.length) {
          throw new Error('backtest_only mode should hide event markers');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_candles_only_mode_hides_backtest_overlays():
    result = _run_workspace_script(r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'run-candles-only',
            metrics: { sharpe: 1.1 },
            equity_curve: [{ date: '2026-04-20', equity: 2 }],
            signals: [{ date: '2026-04-20', signal: 1, signal_strength: 1 }],
            trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-20', pnl_pct: 0.04 }]
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const mode = document.querySelector('[name="chart_display_mode"]');
        mode.value = 'candles_only';
        mode.dispatchEvent({ type: 'change' });

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.displayMode !== 'candles_only') {
          throw new Error('chart did not receive candles_only mode');
        }
        if (latestConfig.equityCurve && latestConfig.equityCurve.length) {
          throw new Error('candles_only mode should hide equity overlays');
        }
        if (latestConfig.signals && latestConfig.signals.length) {
          throw new Error('candles_only mode should hide signal overlays');
        }
        if (latestConfig.trades && latestConfig.trades.length) {
          throw new Error('candles_only mode should hide trade overlays');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_kline_workspace_js.py::test_workspace_js_backtest_panel_has_chart_mode_control tests/test_kline_workspace_js.py::test_workspace_js_backtest_only_mode_passes_display_mode_and_hides_events tests/test_kline_workspace_js.py::test_workspace_js_candles_only_mode_hides_backtest_overlays -q --basetemp .pytest_tmp\biotech-task2-fail
```

Expected: FAIL because `chart_display_mode` is not implemented.

- [ ] **Step 3: Add select helper in workspace JS**

In `static/kline/workspace.js`, add this helper after `addInput`:

```javascript
  function addSelect(form, labelText, name, options, value) {
    var label = makeElement("label", { text: labelText });
    var select = makeElement("select");
    select.name = name;
    options.forEach(function (option) {
      var node = makeElement("option", { text: option.label });
      node.value = option.value;
      select.appendChild(node);
    });
    select.value = value;
    label.appendChild(select);
    form.appendChild(label);
    return select;
  }
```

Add this constant near `EVENT_LAYER_KINDS`:

```javascript
  var CHART_DISPLAY_MODES = [
    { value: "candles_with_backtest", label: "Candles + Backtest" },
    { value: "backtest_only", label: "Backtest Only" },
    { value: "candles_only", label: "Candles Only" }
  ];
```

- [ ] **Step 4: Pass chart display mode into `renderChart`**

Update `renderChart` in `static/kline/workspace.js` so the `window.PokieChart.render` config uses this logic:

```javascript
    var chartMode = state.chartDisplayMode || "candles_with_backtest";
    var showBacktestOverlay = state.showBacktest && chartMode !== "candles_only";
    var showSignalOverlays = showBacktestOverlay && chartMode === "candles_with_backtest";
    var showEventMarkers = chartMode !== "backtest_only";

    var cleanup = window.PokieChart.render(container, {
      displayMode: chartMode,
      ohlcData: (workspace.price && workspace.price.rows) || [],
      events: showEventMarkers ? activeEvents(workspace, state) : [],
      highlightedEventId: showEventMarkers ? state.selectedEventId : null,
      equityCurve: showBacktestOverlay ? state.equityCurve : [],
      signals: showSignalOverlays ? state.signals : [],
      trades: showSignalOverlays ? state.trades : [],
      onEventClick: function (event) {
        if (!showEventMarkers) {
          return;
        }
        state.selectedEventId = event && event.id;
        renderCatalysts(workspace, state);
        renderDetails(workspace, state);
        activatePanel("details");
        renderChart(workspace, state);
      },
```

Keep the existing `onHover` and `onRangeSelect` callbacks below this block.

- [ ] **Step 5: Render and wire the Backtest chart mode selector**

In `renderBacktest`, after the existing risk inputs, add:

```javascript
    state.chartDisplayMode = state.chartDisplayMode || "candles_with_backtest";
    var chartModeSelect = addSelect(
      form,
      "Chart Mode",
      "chart_display_mode",
      CHART_DISPLAY_MODES,
      state.chartDisplayMode
    );
    chartModeSelect.addEventListener("change", function () {
      state.chartDisplayMode = chartModeSelect.value || "candles_with_backtest";
      renderChart(workspace, state);
    });
```

- [ ] **Step 6: Style selects and Backtest status for dark mode**

In `static/kline/workspace.css`, update the shared input rules:

```css
.kline-workspace button,
.kline-workspace input,
.kline-workspace select {
  font: inherit;
}

.ticker-form input,
.backtest-form input,
.backtest-form select {
  background: #0d1016;
  border: 1px solid var(--kline-border);
  border-radius: 6px;
  color: var(--kline-text);
  min-width: 0;
  outline: none;
  padding: 7px 8px;
}

.ticker-form input:focus,
.backtest-form input:focus,
.backtest-form select:focus {
  border-color: var(--kline-cyan);
  box-shadow: 0 0 0 2px rgba(50, 199, 217, 0.18);
}

.backtest-results,
.backtest-status {
  background: #12161d;
  border: 1px solid var(--kline-border-soft);
  border-radius: 6px;
  color: var(--kline-text);
}
```

- [ ] **Step 7: Run task tests**

Run:

```powershell
pytest tests/test_kline_workspace_js.py -q --basetemp .pytest_tmp\biotech-task2
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

Run:

```powershell
git add static\kline\workspace.js static\kline\workspace.css tests\test_kline_workspace_js.py
git commit -m "feat: add backtest chart display modes"
```

---

### Task 3: Make The React Chart Honor Display Modes

**Files:**

- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/index.tsx`
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Modify: `tests/test_kline_static_bundle.py`
- Build output: `static/vendor/pokie-chart.umd.js`
- Build output: `static/vendor/pokie-chart.css`

- [ ] **Step 1: Add failing static bundle tests**

Add this test to `tests/test_kline_static_bundle.py`:

```python
def test_kline_chart_display_modes_hide_candles_and_overlays():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src/kline/chart/CandlestickChart.tsx").read_text()
    types = (repo_root / "src/kline/chart/types.ts").read_text()
    index = (repo_root / "src/kline/chart/index.tsx").read_text()
    bundle = (repo_root / "static/vendor/pokie-chart.umd.js").read_text()

    assert "ChartDisplayMode" in types
    assert "displayMode?: ChartDisplayMode" in types
    assert "displayMode={config.displayMode}" in index
    assert "shouldRenderCandles" in source
    assert "shouldRenderEvents" in source
    assert "shouldRenderBacktestLine" in source
    assert "backtest_only" in source
    assert "candles_only" in source
    assert "backtest_only" in bundle
    assert "candles_only" in bundle
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
pytest tests/test_kline_static_bundle.py::test_kline_chart_display_modes_hide_candles_and_overlays -q --basetemp .pytest_tmp\biotech-task3-fail
```

Expected: FAIL because chart display mode types and branches do not exist.

- [ ] **Step 3: Add chart mode type**

In `src/kline/chart/types.ts`, add:

```typescript
export type ChartDisplayMode = 'candles_with_backtest' | 'backtest_only' | 'candles_only';
```

Add this field to `ChartConfig`:

```typescript
  displayMode?: ChartDisplayMode;
```

- [ ] **Step 4: Pass display mode through the chart entrypoint**

In `src/kline/chart/index.tsx`, update the type export:

```typescript
export type { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, EquityPoint, SignalMarker, TradeMarker, ChartDisplayMode, ChartConfig } from './types';
```

Add this prop to the `CandlestickChart` component:

```typescript
      displayMode={config.displayMode}
```

- [ ] **Step 5: Add render gates to `CandlestickChart`**

In `src/kline/chart/CandlestickChart.tsx`, update the import:

```typescript
import { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, SignalMarker, TradeMarker, ChartDisplayMode } from './types';
```

Add to `Props`:

```typescript
  displayMode?: ChartDisplayMode;
```

Add `displayMode` to the function destructuring and add these constants after `useState`:

```typescript
  const resolvedDisplayMode: ChartDisplayMode = displayMode ?? 'candles_with_backtest';
  const shouldRenderCandles = resolvedDisplayMode !== 'backtest_only';
  const shouldRenderEvents = resolvedDisplayMode === 'candles_with_backtest';
  const shouldRenderBacktestLine = resolvedDisplayMode !== 'candles_only';
  const shouldRenderTradeAndSignalOverlays = resolvedDisplayMode === 'candles_with_backtest';
```

- [ ] **Step 6: Gate chart drawing**

In `drawChart`, wrap the equity curve block with:

```typescript
    if (shouldRenderBacktestLine && mappedEquityCurve.length > 0) {
```

Wrap candlestick drawing with:

```typescript
    if (shouldRenderCandles) {
      const candles = g.selectAll('.candle').data(data).enter().append('g').attr('class', 'candle');

      candles.append('line')
        .attr('x1', (d) => x(d.date))
        .attr('x2', (d) => x(d.date))
        .attr('y1', (d) => y(d.high))
        .attr('y2', (d) => y(d.low))
        .attr('stroke', (d) => (d.close >= d.open ? '#00e676' : '#ff5252'))
        .attr('stroke-width', 1);

      candles.append('rect')
        .attr('x', (d) => x(d.date) - candleWidth / 2)
        .attr('y', (d) => y(Math.max(d.open, d.close)))
        .attr('width', candleWidth)
        .attr('height', (d) => Math.max(1, Math.abs(y(d.open) - y(d.close))))
        .attr('fill', (d) => (d.close >= d.open ? '#00e676' : '#ff5252'));
    }
```

Change trade and signal overlay guards to:

```typescript
    if (shouldRenderTradeAndSignalOverlays && trades && trades.length > 0) {
```

and:

```typescript
    if (shouldRenderTradeAndSignalOverlays && signals && signals.length > 0) {
```

Before event placement, add:

```typescript
    const visibleEventList = shouldRenderEvents ? eventList : [];
```

Use `visibleEventList` instead of `eventList` in the event grouping loop and anomaly scan. If events are hidden, call `placedRef.current = []` and `drawEvents()` after canvas sizing so stale canvas particles disappear.

- [ ] **Step 7: Build chart bundle**

Run:

```powershell
npm run build --prefix src\kline
```

Expected: command exits 0 and updates `static/vendor/pokie-chart.umd.js`.

- [ ] **Step 8: Run chart tests**

Run:

```powershell
pytest tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp\biotech-task3
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```powershell
git add src\kline\chart\types.ts src\kline\chart\index.tsx src\kline\chart\CandlestickChart.tsx static\vendor\pokie-chart.umd.js static\vendor\pokie-chart.css tests\test_kline_static_bundle.py
git commit -m "feat: honor backtest chart display modes"
```

---

### Task 4: Add Biotech Universe Builder And Catalog Metadata

**Files:**

- Create: `src/backtest/universe_builder.py`
- Modify: `src/backtest/research_db.py`
- Create: `tests/test_biotech_universe_builder.py`

- [ ] **Step 1: Add failing universe builder tests**

Create `tests/test_biotech_universe_builder.py`:

```python
from __future__ import annotations

import json


def test_universe_builder_merges_sources_and_excludes_benchmark_etfs():
    from src.backtest.universe_builder import (
        BIOTECH_US_UNIVERSE_ID,
        UniverseSourceRow,
        build_universe_snapshot,
    )

    rows = [
        UniverseSourceRow(ticker="MRNA", company_name="Moderna, Inc.", exchange="NASDAQ", asset_type="common_stock", source="xbi", source_weight=0.012),
        UniverseSourceRow(ticker="MRNA", company_name="Moderna Inc", exchange="NASDAQ", asset_type="common_stock", source="ibb", source_weight=0.018),
        UniverseSourceRow(ticker="XBI", company_name="SPDR S&P Biotech ETF", exchange="NYSEARCA", asset_type="etf", source="xbi", source_weight=1.0),
        UniverseSourceRow(ticker="DNA", company_name="Ginkgo Bioworks Holdings, Inc.", exchange="NYSE", asset_type="common_stock", source="nasdaq_screener", industry="Biotechnology"),
    ]

    snapshot = build_universe_snapshot(rows, as_of_date="2026-05-08")

    assert snapshot.universe_id == BIOTECH_US_UNIVERSE_ID
    assert [member.ticker for member in snapshot.members] == ["DNA", "MRNA"]
    assert snapshot.benchmark_tickers == ("XBI",)
    assert snapshot.bias_status == "current_constituents_only"
    assert snapshot.survivorship_bias_warning is True
    mrna = next(member for member in snapshot.members if member.ticker == "MRNA")
    assert mrna.source_memberships == ("ibb", "xbi")


def test_universe_snapshot_serializes_bias_metadata():
    from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot

    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(ticker="MRNA", company_name="Moderna, Inc.", exchange="NASDAQ", asset_type="common_stock", source="xbi"),
        ],
        as_of_date="2026-05-08",
    )

    payload = snapshot.to_catalog_payload()
    assert payload["universe_id"] == "biotech_us_v1"
    assert payload["as_of_date"] == "2026-05-08"
    assert payload["bias_status"] == "current_constituents_only"
    assert payload["survivorship_bias_warning"] is True
    assert json.loads(payload["coverage_json"]) == {
        "benchmark_tickers": [],
        "member_count": 1,
        "sources": ["xbi"],
    }
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_biotech_universe_builder.py -q --basetemp .pytest_tmp\biotech-task4-fail
```

Expected: FAIL because `src.backtest.universe_builder` does not exist.

- [ ] **Step 3: Add universe snapshot table**

In `src/backtest/research_db.py`, add this statement to `CATALOG_SQL` before `data_snapshots`:

```python
    """
    CREATE TABLE IF NOT EXISTS universe_snapshots (
        universe_snapshot_id TEXT PRIMARY KEY,
        universe_id TEXT,
        as_of_date DATE,
        bias_status TEXT,
        survivorship_bias_warning BOOLEAN,
        member_count INTEGER,
        benchmark_tickers_json TEXT,
        source_payload_json TEXT,
        coverage_json TEXT,
        created_at TIMESTAMP
    )
    """,
```

- [ ] **Step 4: Create universe builder module**

Create `src/backtest/universe_builder.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

BIOTECH_US_UNIVERSE_ID = "biotech_us_v1"
BENCHMARK_ASSET_TYPES = {"etf", "benchmark_etf", "fund"}
CURRENT_CONSTITUENTS_BIAS_STATUS = "current_constituents_only"


@dataclass(frozen=True)
class UniverseSourceRow:
    ticker: str
    company_name: str
    exchange: str
    asset_type: str
    source: str
    source_weight: float | None = None
    industry: str | None = None
    cik: str | None = None
    cusip: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class UniverseMember:
    security_id: str
    ticker: str
    company_name: str
    exchange: str
    asset_type: str
    source_memberships: tuple[str, ...]
    cik: str | None = None
    cusip: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_snapshot_id: str
    universe_id: str
    as_of_date: str
    members: tuple[UniverseMember, ...]
    benchmark_tickers: tuple[str, ...]
    bias_status: str
    survivorship_bias_warning: bool
    source_payloads: tuple[dict, ...]

    def to_catalog_payload(self) -> dict:
        sources = sorted(
            {
                source
                for member in self.members
                for source in member.source_memberships
            }
        )
        coverage = {
            "benchmark_tickers": list(self.benchmark_tickers),
            "member_count": len(self.members),
            "sources": sources,
        }
        return {
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_id": self.universe_id,
            "as_of_date": self.as_of_date,
            "bias_status": self.bias_status,
            "survivorship_bias_warning": self.survivorship_bias_warning,
            "member_count": len(self.members),
            "benchmark_tickers_json": json.dumps(list(self.benchmark_tickers), sort_keys=True),
            "source_payload_json": json.dumps(list(self.source_payloads), sort_keys=True),
            "coverage_json": json.dumps(coverage, sort_keys=True),
        }


def build_universe_snapshot(
    rows: Iterable[UniverseSourceRow],
    *,
    as_of_date: str,
    universe_id: str = BIOTECH_US_UNIVERSE_ID,
) -> UniverseSnapshot:
    grouped: dict[str, list[UniverseSourceRow]] = {}
    benchmarks: set[str] = set()
    source_payloads = []

    for row in rows:
        ticker = _normalize_ticker(row.ticker)
        source_payloads.append(_row_payload(row, ticker=ticker))
        if _is_benchmark(row):
            benchmarks.add(ticker)
            continue
        grouped.setdefault(ticker, []).append(row)

    members = tuple(
        _member_from_rows(ticker, grouped[ticker])
        for ticker in sorted(grouped)
    )
    snapshot_id = _snapshot_id(
        universe_id=universe_id,
        as_of_date=as_of_date,
        members=members,
        benchmarks=tuple(sorted(benchmarks)),
    )
    return UniverseSnapshot(
        universe_snapshot_id=snapshot_id,
        universe_id=universe_id,
        as_of_date=as_of_date,
        members=members,
        benchmark_tickers=tuple(sorted(benchmarks)),
        bias_status=CURRENT_CONSTITUENTS_BIAS_STATUS,
        survivorship_bias_warning=True,
        source_payloads=tuple(source_payloads),
    )


def _member_from_rows(ticker: str, rows: list[UniverseSourceRow]) -> UniverseMember:
    first = rows[0]
    sources = tuple(sorted({_normalize_source(row.source) for row in rows}))
    return UniverseMember(
        security_id=f"BIO:{ticker}",
        ticker=ticker,
        company_name=first.company_name.strip(),
        exchange=first.exchange.strip().upper(),
        asset_type=first.asset_type.strip().lower(),
        source_memberships=sources,
        cik=_clean_optional(first.cik),
        cusip=_clean_optional(first.cusip),
        isin=_clean_optional(first.isin),
    )


def _is_benchmark(row: UniverseSourceRow) -> bool:
    return row.asset_type.strip().lower() in BENCHMARK_ASSET_TYPES


def _row_payload(row: UniverseSourceRow, *, ticker: str) -> dict:
    return {
        "ticker": ticker,
        "company_name": row.company_name,
        "exchange": row.exchange,
        "asset_type": row.asset_type,
        "source": _normalize_source(row.source),
        "source_weight": row.source_weight,
        "industry": row.industry,
        "cik": row.cik,
        "cusip": row.cusip,
        "isin": row.isin,
    }


def _snapshot_id(
    *,
    universe_id: str,
    as_of_date: str,
    members: tuple[UniverseMember, ...],
    benchmarks: tuple[str, ...],
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "benchmarks": benchmarks,
        "members": [member.__dict__ for member in members],
        "universe_id": universe_id,
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"univ_{as_of_date.replace('-', '')}_{digest}"


def _normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def _normalize_source(value: str) -> str:
    source = value.strip().lower()
    if not source:
        raise ValueError("source is required")
    return source


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
```

- [ ] **Step 5: Run task tests**

Run:

```powershell
pytest tests/test_biotech_universe_builder.py -q --basetemp .pytest_tmp\biotech-task4
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add src\backtest\research_db.py src\backtest\universe_builder.py tests\test_biotech_universe_builder.py
git commit -m "feat: add biotech universe snapshot builder"
```

---

### Task 5: Add Rate Limit And Provider Fetch Log Infrastructure

**Files:**

- Create: `src/data_ingestion/__init__.py`
- Create: `src/data_ingestion/rate_limit.py`
- Create: `src/data_ingestion/provider_log.py`
- Modify: `src/backtest/research_db.py`
- Create: `tests/test_provider_rate_limit.py`
- Create: `tests/test_provider_fetch_log.py`

- [ ] **Step 1: Add failing tests**

Create `tests/test_provider_rate_limit.py`:

```python
from __future__ import annotations


def test_fixed_window_rate_limit_blocks_after_budget():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limit = FixedWindowRateLimit(max_requests=2, window_seconds=60)

    assert limit.allow("tiingo", now=100.0).allowed is True
    assert limit.allow("tiingo", now=101.0).allowed is True
    blocked = limit.allow("tiingo", now=102.0)

    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 58.0


def test_fixed_window_rate_limit_is_provider_scoped():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limit = FixedWindowRateLimit(max_requests=1, window_seconds=60)

    assert limit.allow("tiingo", now=100.0).allowed is True
    assert limit.allow("fmp", now=100.0).allowed is True
    assert limit.allow("tiingo", now=101.0).allowed is False
```

Create `tests/test_provider_fetch_log.py`:

```python
from __future__ import annotations

import json


def test_provider_fetch_log_records_rate_limit_status(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.data_ingestion.provider_log import record_provider_fetch

    db_path = tmp_path / "research.duckdb"
    initialize_research_database(db_path)

    record_provider_fetch(
        db_path=db_path,
        provider="tiingo",
        endpoint="daily/MRNA/prices",
        request_hash="abc123",
        status="rate_limited",
        retry_count=2,
        message="HTTP 429",
        metadata={"retry_after_seconds": 30},
    )

    import duckdb

    conn = duckdb.connect(str(db_path))
    row = conn.execute(
        """
        SELECT provider, endpoint, request_hash, status, retry_count, message, metadata_json
        FROM provider_fetch_log
        """
    ).fetchone()
    conn.close()

    assert row[:6] == ("tiingo", "daily/MRNA/prices", "abc123", "rate_limited", 2, "HTTP 429")
    assert json.loads(row[6]) == {"retry_after_seconds": 30}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_provider_rate_limit.py tests/test_provider_fetch_log.py -q --basetemp .pytest_tmp\biotech-task5-fail
```

Expected: FAIL because ingestion modules and `provider_fetch_log` do not exist.

- [ ] **Step 3: Add provider fetch log table**

In `src/backtest/research_db.py`, add to `CATALOG_SQL`:

```python
    """
    CREATE TABLE IF NOT EXISTS provider_fetch_log (
        fetch_id TEXT PRIMARY KEY,
        provider TEXT,
        endpoint TEXT,
        request_hash TEXT,
        status TEXT,
        retry_count INTEGER,
        message TEXT,
        metadata_json TEXT,
        created_at TIMESTAMP
    )
    """,
```

- [ ] **Step 4: Create rate limiter**

Create `src/data_ingestion/__init__.py` as an empty file.

Create `src/data_ingestion/rate_limit.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float


class FixedWindowRateLimit:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = float(window_seconds)
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, provider: str, *, now: float) -> RateLimitDecision:
        key = provider.strip().lower()
        if not key:
            raise ValueError("provider is required")
        window_start, count = self._windows.get(key, (now, 0))
        if now - window_start >= self.window_seconds:
            window_start = now
            count = 0
        if count >= self.max_requests:
            retry_after = max(0.0, self.window_seconds - (now - window_start))
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
        self._windows[key] = (window_start, count + 1)
        return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
```

- [ ] **Step 5: Create provider log writer**

Create `src/data_ingestion/provider_log.py`:

```python
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


def record_provider_fetch(
    *,
    db_path: str | Path | None = None,
    provider: str,
    endpoint: str,
    request_hash: str,
    status: str,
    retry_count: int,
    message: str,
    metadata: dict | None = None,
) -> str:
    provider = provider.strip().lower()
    endpoint = endpoint.strip()
    request_hash = request_hash.strip()
    status = status.strip().lower()
    if not provider or not endpoint or not request_hash or not status:
        raise ValueError("provider, endpoint, request_hash, and status are required")
    metadata_json = json.dumps(metadata or {}, sort_keys=True)
    fetch_id = sha256(
        "|".join([provider, endpoint, request_hash, status, str(retry_count), metadata_json]).encode("utf-8")
    ).hexdigest()
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO provider_fetch_log (
                fetch_id,
                provider,
                endpoint,
                request_hash,
                status,
                retry_count,
                message,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                fetch_id,
                provider,
                endpoint,
                request_hash,
                status,
                int(retry_count),
                message,
                metadata_json,
            ],
        )
    finally:
        conn.close()
    return fetch_id
```

- [ ] **Step 6: Run task tests**

Run:

```powershell
pytest tests/test_provider_rate_limit.py tests/test_provider_fetch_log.py -q --basetemp .pytest_tmp\biotech-task5
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git add src\data_ingestion\__init__.py src\data_ingestion\rate_limit.py src\data_ingestion\provider_log.py src\backtest\research_db.py tests\test_provider_rate_limit.py tests\test_provider_fetch_log.py
git commit -m "feat: add provider rate limit fetch logging"
```

---

### Task 6: Add Tiingo Daily OHLCV Normalization

**Files:**

- Create: `src/data_ingestion/tiingo_prices.py`
- Modify: `src/backtest/data_sources.py`
- Modify: `src/backtest/price_snapshot.py`
- Modify: `tests/test_backtest_data_sources.py`
- Create: `tests/test_tiingo_price_ingestion.py`

- [ ] **Step 1: Add failing Tiingo source tests**

Append to `tests/test_backtest_data_sources.py`:

```python
def test_tiingo_profile_is_formal_exploratory_source_with_unknown_survivorship_bias():
    from src.backtest.data_sources import BiasProfile, TIINGO_PROFILE

    assert TIINGO_PROFILE.source_id == "tiingo"
    assert TIINGO_PROFILE.bias_profile == BiasProfile.UNKNOWN_BIAS
    assert TIINGO_PROFILE.supports_delisted is False
    assert TIINGO_PROFILE.supports_point_in_time_universe is False
    assert TIINGO_PROFILE.supports_delisting_returns is False
```

Create `tests/test_tiingo_price_ingestion.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest


def test_normalize_tiingo_prices_keeps_adjusted_fields():
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    frame = normalize_tiingo_eod_prices(
        [
            {
                "date": "2026-05-01T00:00:00.000Z",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "adjOpen": 9.8,
                "adjHigh": 10.8,
                "adjLow": 9.3,
                "adjClose": 10.2,
                "adjVolume": 1020,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )

    row = frame.iloc[0]
    assert row["security_id"] == "TIINGO:MRNA"
    assert row["source"] == "tiingo"
    assert row["adjustment_mode"] == "tiingo_adjusted"
    assert row["adjustment_quality"] == "adjusted"
    assert row["adj_close"] == 10.2
    assert row["split_factor"] == 1.0
    assert row["dividend"] == 0.0


def test_normalize_tiingo_prices_rejects_missing_adjusted_close():
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    with pytest.raises(ValueError, match="adjClose"):
        normalize_tiingo_eod_prices(
            [
                {
                    "date": "2026-05-01T00:00:00.000Z",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1000,
                }
            ],
            ticker="MRNA",
            data_snapshot_id="snap-tiingo",
        )


def test_tiingo_prices_can_be_written_to_price_partitions(tmp_path):
    from src.backtest.price_snapshot import write_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    frame = normalize_tiingo_eod_prices(
        [
            {
                "date": "2026-05-01T00:00:00.000Z",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "adjOpen": 9.8,
                "adjHigh": 10.8,
                "adjLow": 9.3,
                "adjClose": 10.2,
                "adjVolume": 1020,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ],
        ticker="MRNA",
        data_snapshot_id="snap-tiingo",
    )
    write_prices_daily_frame(frame, output_root=tmp_path / "prices_daily")

    files = list((tmp_path / "prices_daily").rglob("*.parquet"))
    assert len(files) == 1
    prices = pd.read_parquet(files[0])
    assert prices.iloc[0]["source"] == "tiingo"
    assert prices.iloc[0]["adjustment_quality"] == "adjusted"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_backtest_data_sources.py::test_tiingo_profile_is_formal_exploratory_source_with_unknown_survivorship_bias tests/test_tiingo_price_ingestion.py -q --basetemp .pytest_tmp\biotech-task6-fail
```

Expected: FAIL because Tiingo source profile and normalizer do not exist.

- [ ] **Step 3: Add Tiingo source profile**

In `src/backtest/data_sources.py`, add:

```python
TIINGO_PROFILE = SourceProfile(
    source_id="tiingo",
    display_name="Tiingo End-of-Day",
    bias_profile=BiasProfile.UNKNOWN_BIAS,
    supports_delisted=False,
    supports_point_in_time_universe=False,
    supports_delisting_returns=False,
)
```

Keep `RESEARCH_GRADE` blocked for Tiingo until point-in-time universe and delisting-return coverage are available.

- [ ] **Step 4: Add adjusted columns to price schema**

In `src/backtest/price_snapshot.py`, extend `PRICE_COLUMNS` after `adj_close`:

```python
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_volume",
```

Add:

```python
    "adjustment_quality",
```

after `adjustment_mode`.

Extend `FLOAT_COLUMNS` with:

```python
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_volume",
```

In `normalize_ohlc_frame`, set yfinance cache imports as raw-only:

```python
    df["adj_open"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_high"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_low"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_close"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adj_volume"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["adjustment_mode"] = "raw_ohlc_cache"
    df["adjustment_quality"] = "raw_only"
```

Add a public writer:

```python
def write_prices_daily_frame(
    frame: pd.DataFrame,
    *,
    output_root: str | Path | None = None,
) -> None:
    root = Path(output_root) if output_root is not None else RESEARCH_DIR / "prices_daily"
    missing = set(PRICE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"prices_daily frame missing columns: {sorted(missing)}")
    for source in sorted(frame["source"].unique()):
        for snapshot_id in sorted(frame["data_snapshot_id"].unique()):
            subset = frame[
                (frame["source"] == source)
                & (frame["data_snapshot_id"] == snapshot_id)
            ]
            _write_partition(
                subset[PRICE_COLUMNS],
                root,
                source=str(source),
                data_snapshot_id=str(snapshot_id),
            )
```

Update `_validate_source` to accept yfinance and tiingo:

```python
    allowed = {YFINANCE_PROFILE.source_id, "tiingo"}
    if source not in allowed:
        raise ValueError(
            f"Unsupported OHLC source {source!r}; expected one of {sorted(allowed)!r}."
        )
```

- [ ] **Step 5: Create Tiingo normalizer**

Create `src/data_ingestion/tiingo_prices.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.backtest.price_snapshot import PRICE_COLUMNS

REQUIRED_TIINGO_FIELDS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjOpen",
    "adjHigh",
    "adjLow",
    "adjClose",
    "adjVolume",
    "divCash",
    "splitFactor",
}


def normalize_tiingo_eod_prices(
    rows: list[dict],
    *,
    ticker: str,
    data_snapshot_id: str,
) -> pd.DataFrame:
    missing = REQUIRED_TIINGO_FIELDS - set().union(*(row.keys() for row in rows or [{}]))
    if missing:
        raise ValueError(f"Tiingo EOD rows missing fields: {sorted(missing)}")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.date
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjOpen",
        "adjHigh",
        "adjLow",
        "adjClose",
        "adjVolume",
        "divCash",
        "splitFactor",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", *numeric_columns])
    finite = np.isfinite(df[numeric_columns]).all(axis=1)
    df = df[finite]
    valid = (
        (df[["open", "high", "low", "close", "adjOpen", "adjHigh", "adjLow", "adjClose"]] > 0).all(axis=1)
        & (df["volume"] >= 0)
        & (df["adjVolume"] >= 0)
        & (df["high"] >= df["low"])
        & (df["adjHigh"] >= df["adjLow"])
    )
    df = df[valid].copy()
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    symbol = ticker.strip().upper()
    ingested_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    normalized = pd.DataFrame(
        {
            "security_id": f"TIINGO:{symbol}",
            "ticker": symbol,
            "date": df["date"],
            "open": df["open"].astype("float64"),
            "high": df["high"].astype("float64"),
            "low": df["low"].astype("float64"),
            "close": df["close"].astype("float64"),
            "adj_open": df["adjOpen"].astype("float64"),
            "adj_high": df["adjHigh"].astype("float64"),
            "adj_low": df["adjLow"].astype("float64"),
            "adj_close": df["adjClose"].astype("float64"),
            "adj_volume": df["adjVolume"].astype("float64"),
            "volume": df["volume"].astype("float64"),
            "vwap": pd.Series(float("nan"), index=df.index, dtype="float64"),
            "split_factor": df["splitFactor"].astype("float64"),
            "dividend": df["divCash"].astype("float64"),
            "delisting_return": pd.Series(float("nan"), index=df.index, dtype="float64"),
            "adjustment_mode": "tiingo_adjusted",
            "adjustment_quality": "adjusted",
            "source": "tiingo",
            "source_symbol": symbol,
            "data_snapshot_id": data_snapshot_id,
            "ingested_at": ingested_at,
        }
    )
    duplicates = normalized.duplicated(subset=["security_id", "date"], keep=False)
    if duplicates.any():
        raise ValueError("Duplicate Tiingo price rows for security/date")
    return normalized[PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)
```

- [ ] **Step 6: Run price/data source tests**

Run:

```powershell
pytest tests/test_backtest_data_sources.py tests/test_backtest_price_snapshot.py tests/test_tiingo_price_ingestion.py -q --basetemp .pytest_tmp\biotech-task6
```

Expected: PASS after updating `tests/test_backtest_price_snapshot.py` column expectations for `adj_open`, `adj_high`, `adj_low`, `adj_volume`, and `adjustment_quality`.

- [ ] **Step 7: Commit Task 6**

Run:

```powershell
git add src\backtest\data_sources.py src\backtest\price_snapshot.py src\data_ingestion\tiingo_prices.py tests\test_backtest_data_sources.py tests\test_backtest_price_snapshot.py tests\test_tiingo_price_ingestion.py
git commit -m "feat: add tiingo daily price normalization"
```

---

### Task 7: Add FMP And SEC Fundamental Normalization

**Files:**

- Create: `src/data_ingestion/fundamentals.py`
- Modify: `src/backtest/research_db.py`
- Create: `tests/test_fundamentals_ingestion.py`

- [ ] **Step 1: Add failing fundamentals tests**

Create `tests/test_fundamentals_ingestion.py`:

```python
from __future__ import annotations


def test_normalize_fmp_statement_extracts_biotech_burn_fields():
    from src.data_ingestion.fundamentals import normalize_fmp_financial_statements

    rows = normalize_fmp_financial_statements(
        ticker="MRNA",
        statements=[
            {
                "date": "2026-03-31",
                "period": "Q1",
                "calendarYear": "2026",
                "fillingDate": "2026-05-05",
                "acceptedDate": "2026-05-05 16:30:00",
                "reportedCurrency": "USD",
                "cashAndCashEquivalents": 1000,
                "shortTermInvestments": 200,
                "totalDebt": 50,
                "operatingCashFlow": -120,
                "researchAndDevelopmentExpenses": 300,
                "sellingGeneralAndAdministrativeExpenses": 80,
                "revenue": 25,
                "netIncome": -180,
            }
        ],
        source="fmp",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "MRNA"
    assert row["fiscal_period"] == "2026-Q1"
    assert row["cash_and_short_term_investments"] == 1200.0
    assert row["operating_cash_flow"] == -120.0
    assert row["cash_runway_quarters"] == 10.0
    assert row["source"] == "fmp"


def test_normalize_sec_company_facts_keeps_cik_and_concept_source():
    from src.data_ingestion.fundamentals import normalize_sec_company_facts

    rows = normalize_sec_company_facts(
        cik="0001682852",
        ticker="MRNA",
        companyfacts={
            "facts": {
                "us-gaap": {
                    "CashAndCashEquivalentsAtCarryingValue": {
                        "units": {
                            "USD": [
                                {
                                    "fy": 2026,
                                    "fp": "Q1",
                                    "form": "10-Q",
                                    "filed": "2026-05-05",
                                    "end": "2026-03-31",
                                    "val": 1000,
                                }
                            ]
                        }
                    }
                }
            }
        },
    )

    assert rows == [
        {
            "security_id": "SEC:0001682852",
            "ticker": "MRNA",
            "cik": "0001682852",
            "taxonomy": "us-gaap",
            "concept": "CashAndCashEquivalentsAtCarryingValue",
            "unit": "USD",
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "form": "10-Q",
            "filed": "2026-05-05",
            "period_end": "2026-03-31",
            "value": 1000.0,
            "source": "sec_companyfacts",
        }
    ]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_fundamentals_ingestion.py -q --basetemp .pytest_tmp\biotech-task7-fail
```

Expected: FAIL because `src.data_ingestion.fundamentals` does not exist.

- [ ] **Step 3: Add fundamentals catalog tables**

In `src/backtest/research_db.py`, add:

```python
    """
    CREATE TABLE IF NOT EXISTS fundamentals_normalized (
        security_id TEXT,
        ticker TEXT,
        fiscal_period TEXT,
        filing_date DATE,
        source TEXT,
        payload_json TEXT,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sec_companyfacts_normalized (
        security_id TEXT,
        ticker TEXT,
        cik TEXT,
        taxonomy TEXT,
        concept TEXT,
        unit TEXT,
        fiscal_year INTEGER,
        fiscal_period TEXT,
        form TEXT,
        filed DATE,
        period_end DATE,
        value DOUBLE,
        source TEXT,
        created_at TIMESTAMP
    )
    """,
```

- [ ] **Step 4: Create fundamentals normalizer**

Create `src/data_ingestion/fundamentals.py`:

```python
from __future__ import annotations

from typing import Any


def normalize_fmp_financial_statements(
    *,
    ticker: str,
    statements: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    symbol = ticker.strip().upper()
    rows = []
    for statement in statements:
        fiscal_year = str(statement.get("calendarYear") or "").strip()
        period = str(statement.get("period") or "").strip()
        fiscal_period = f"{fiscal_year}-{period}" if fiscal_year and period else ""
        cash = _number(statement.get("cashAndCashEquivalents"))
        short_term_investments = _number(statement.get("shortTermInvestments"))
        operating_cash_flow = _number(statement.get("operatingCashFlow"))
        cash_and_investments = cash + short_term_investments
        quarterly_burn = abs(operating_cash_flow) if operating_cash_flow < 0 else 0.0
        cash_runway_quarters = None
        if quarterly_burn > 0:
            cash_runway_quarters = round(cash_and_investments / quarterly_burn, 6)
        rows.append(
            {
                "security_id": f"FMP:{symbol}",
                "ticker": symbol,
                "fiscal_period": fiscal_period,
                "period_end": statement.get("date"),
                "filing_date": statement.get("fillingDate"),
                "accepted_date": statement.get("acceptedDate"),
                "currency": statement.get("reportedCurrency"),
                "cash_and_equivalents": cash,
                "short_term_investments": short_term_investments,
                "cash_and_short_term_investments": cash_and_investments,
                "total_debt": _number(statement.get("totalDebt")),
                "operating_cash_flow": operating_cash_flow,
                "rd_expense": _number(statement.get("researchAndDevelopmentExpenses")),
                "sga_expense": _number(statement.get("sellingGeneralAndAdministrativeExpenses")),
                "revenue": _number(statement.get("revenue")),
                "net_income": _number(statement.get("netIncome")),
                "cash_runway_quarters": cash_runway_quarters,
                "source": source,
            }
        )
    return rows


def normalize_sec_company_facts(
    *,
    cik: str,
    ticker: str,
    companyfacts: dict[str, Any],
) -> list[dict[str, Any]]:
    symbol = ticker.strip().upper()
    cik_token = cik.strip().zfill(10)
    rows = []
    facts = companyfacts.get("facts") or {}
    for taxonomy, concepts in facts.items():
        for concept, concept_payload in concepts.items():
            units = concept_payload.get("units") or {}
            for unit, values in units.items():
                for value in values:
                    rows.append(
                        {
                            "security_id": f"SEC:{cik_token}",
                            "ticker": symbol,
                            "cik": cik_token,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "fiscal_year": int(value["fy"]),
                            "fiscal_period": str(value["fp"]),
                            "form": str(value["form"]),
                            "filed": str(value["filed"]),
                            "period_end": str(value["end"]),
                            "value": _number(value.get("val")),
                            "source": "sec_companyfacts",
                        }
                    )
    return rows


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)
```

- [ ] **Step 5: Run task tests**

Run:

```powershell
pytest tests/test_fundamentals_ingestion.py -q --basetemp .pytest_tmp\biotech-task7
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

Run:

```powershell
git add src\data_ingestion\fundamentals.py src\backtest\research_db.py tests\test_fundamentals_ingestion.py
git commit -m "feat: normalize biotech fundamentals"
```

---

### Task 8: Load Portfolio Universe From DuckDB Membership

**Files:**

- Create: `src/backtest/universe.py`
- Modify: `src/backtest/portfolio_runner.py`
- Modify: `src/kline/routes.py`
- Modify: `tests/test_kline_backtest_runner.py`
- Modify: `tests/test_kline_web_integration.py`
- Create: `tests/test_biotech_universe_loader.py`

- [ ] **Step 1: Add failing universe loader tests**

Create `tests/test_biotech_universe_loader.py`:

```python
from __future__ import annotations


def test_load_universe_tickers_reads_active_membership(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import load_universe_tickers

    db_path = tmp_path / "research.duckdb"
    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO universe_membership (
            universe_id, security_id, ticker, member_from, member_to, weight,
            membership_source, as_of_date
        )
        VALUES
            ('biotech_us_v1', 'BIO:MRNA', 'MRNA', '2026-05-08', NULL, NULL, 'xbi', '2026-05-08'),
            ('biotech_us_v1', 'BIO:OLD', 'OLD', '2020-01-01', '2021-01-01', NULL, 'delisted_reference', '2026-05-08')
        """
    )
    conn.close()

    assert load_universe_tickers(db_path=db_path, universe_id="biotech_us_v1", as_of_date="2026-05-08") == ("MRNA",)


def test_load_universe_tickers_rejects_mock_universe(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import UnsupportedUniverseError, load_universe_tickers

    db_path = tmp_path / "research.duckdb"
    initialize_research_database(db_path)

    try:
        load_universe_tickers(db_path=db_path, universe_id="biotech_mock_v1", as_of_date="2026-05-08")
    except UnsupportedUniverseError as exc:
        assert str(exc) == "Unsupported production universe: biotech_mock_v1"
    else:
        raise AssertionError("biotech_mock_v1 must be rejected")
```

- [ ] **Step 2: Add failing portfolio runner test**

Add this test to `tests/test_kline_backtest_runner.py`:

```python
def test_real_portfolio_backtest_uses_duckdb_universe(monkeypatch, tmp_path):
    from src.backtest import portfolio_runner
    from src.backtest.research_db import initialize_research_database

    db_path = tmp_path / "research.duckdb"
    initialize_research_database(db_path)

    import duckdb

    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO universe_membership (
            universe_id, security_id, ticker, member_from, member_to, weight,
            membership_source, as_of_date
        )
        VALUES
            ('biotech_us_v1', 'BIO:MRNA', 'MRNA', '2026-05-08', NULL, NULL, 'xbi', '2026-05-08'),
            ('biotech_us_v1', 'BIO:JNJ', 'JNJ', '2026-05-08', NULL, NULL, 'ibb', '2026-05-08')
        """
    )
    conn.close()

    seen = []

    def fake_run_kline_backtest(**kwargs):
        seen.append(kwargs["ticker"])
        return {
            "ticker": kwargs["ticker"],
            "equity_curve": [
                {"date": "2026-05-08", "equity": 1.0},
                {"date": "2026-05-11", "equity": 1.1},
            ],
            "signals": [{"date": "2026-05-08", "signal": 1}],
            "trades": [{"entry_date": "2026-05-08", "exit_date": "2026-05-11", "pnl_pct": 0.1}],
            "metrics": {"sharpe_ratio": 1.2},
            "baseline": {"strategy_return": 0.1},
            "signal_summary": {"active_signal_days": 1},
            "exposure_summary": {"exposure_days": 2},
        }

    monkeypatch.setattr(portfolio_runner, "run_kline_backtest", fake_run_kline_backtest)

    payload = portfolio_runner.run_real_biotech_portfolio_backtest(
        focus_ticker="MRNA",
        start_date="2026-05-08",
        end_date="2026-05-11",
        db_path=db_path,
        universe_id="biotech_us_v1",
        as_of_date="2026-05-08",
    )

    assert seen == ["JNJ", "MRNA"]
    assert payload["universe_id"] == "biotech_us_v1"
    assert payload["data_credibility"]["eligible_universe_count"] == 2
    assert payload["data_credibility"]["survivorship_bias_warning"] is True
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_biotech_universe_loader.py tests/test_kline_backtest_runner.py::test_real_portfolio_backtest_uses_duckdb_universe -q --basetemp .pytest_tmp\biotech-task8-fail
```

Expected: FAIL because `src.backtest.universe` and DB-backed runner parameters do not exist.

- [ ] **Step 4: Create universe loader**

Create `src/backtest/universe.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID


class UnsupportedUniverseError(ValueError):
    pass


def load_universe_tickers(
    *,
    db_path: str | Path | None = None,
    universe_id: str,
    as_of_date: str,
) -> tuple[str, ...]:
    if universe_id != BIOTECH_US_UNIVERSE_ID:
        raise UnsupportedUniverseError(f"Unsupported production universe: {universe_id}")
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT ticker
            FROM universe_membership
            WHERE universe_id = ?
              AND member_from <= ?
              AND (member_to IS NULL OR member_to >= ?)
            ORDER BY ticker
            """,
            [universe_id, as_of_date, as_of_date],
        ).fetchall()
    finally:
        conn.close()
    return tuple(str(row[0]).upper() for row in rows)
```

- [ ] **Step 5: Update portfolio runner constants and signature**

In `src/backtest/portfolio_runner.py`, import:

```python
from pathlib import Path

from src.backtest.universe import load_universe_tickers
from src.backtest.universe_builder import BIOTECH_US_UNIVERSE_ID
```

Change:

```python
BIOTECH_REAL_UNIVERSE_ID = "biotech_four_v1"
BIOTECH_REAL_TICKERS = ("MRNA", "JNJ", "LLY", "XBI")
```

to:

```python
BIOTECH_REAL_UNIVERSE_ID = BIOTECH_US_UNIVERSE_ID
BIOTECH_REAL_TICKERS: tuple[str, ...] = ()
```

Change `run_real_biotech_portfolio_backtest` signature:

```python
def run_real_biotech_portfolio_backtest(
    focus_ticker: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = -0.08,
    max_position_pct: float = 0.2,
    slippage_pct: float = 0.001,
    holding_period_days: int | None = None,
    *,
    db_path: str | Path | None = None,
    universe_id: str = BIOTECH_REAL_UNIVERSE_ID,
    as_of_date: str | None = None,
) -> dict:
```

Inside it, load tickers:

```python
    resolved_as_of_date = as_of_date or end_date
    tickers = load_universe_tickers(
        db_path=db_path,
        universe_id=universe_id,
        as_of_date=resolved_as_of_date,
    )
    if not tickers:
        return {
            "error": f"no eligible tickers for universe {universe_id} as of {resolved_as_of_date}",
            "data_credibility": {
                "eligible_universe_count": 0,
                "skipped_ticker_count": 0,
                "survivorship_bias_warning": True,
            },
        }
```

Replace the existing direct return with this structure:

```python
    payload = _run_biotech_portfolio_backtest(
        focus_ticker=focus_ticker,
        start_date=start_date,
        end_date=end_date,
        universe_id=universe_id,
        tickers=tickers,
        strategy_id=REAL_MULTIFACTOR_STRATEGY_ID,
        data_mode="real",
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        slippage_pct=slippage_pct,
        holding_period_days=holding_period_days,
    )
    if isinstance(payload, dict) and payload.get("error"):
        return payload
    payload["data_credibility"] = {
        "eligible_universe_count": len(tickers),
        "skipped_ticker_count": 0,
        "survivorship_bias_warning": True,
        "universe_bias_status": "current_constituents_only",
    }
    return payload
```

- [ ] **Step 6: Update route to stop rejecting focus ticker against old tuple**

In `src/kline/routes.py`, remove `BIOTECH_REAL_TICKERS` from the
`src.backtest.portfolio_runner` import if it is still present.

Remove this old hard-coded focus ticker check:

```python
    if parsed["ticker"] not in BIOTECH_REAL_TICKERS:
        return (
            jsonify(
                {
                    "error": "portfolio backtest is only available for MRNA, JNJ, LLY, and XBI",
                }
            ),
            400,
        )
```

Update the call:

```python
    result = run_real_biotech_portfolio_backtest(
        focus_ticker=parsed["ticker"],
        start_date=parsed["start_date"],
        end_date=parsed["end_date"],
        stop_loss_pct=parsed["stop_loss_pct"],
        max_position_pct=parsed["max_position_pct"],
        slippage_pct=parsed["slippage_pct"],
        holding_period_days=parsed["holding_period_days"],
        universe_id=(parsed["data"].get("universe_id") or "biotech_us_v1"),
        as_of_date=parsed["end_date"],
    )
```

- [ ] **Step 7: Run universe and runner tests**

Run:

```powershell
pytest tests/test_biotech_universe_loader.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py -q --basetemp .pytest_tmp\biotech-task8
```

Expected: PASS after updating old assertions that expected `biotech_four_v1` for real portfolio runs.

- [ ] **Step 8: Commit Task 8**

Run:

```powershell
git add src\backtest\universe.py src\backtest\portfolio_runner.py src\kline\routes.py tests\test_biotech_universe_loader.py tests\test_kline_backtest_runner.py tests\test_kline_web_integration.py
git commit -m "feat: run portfolio backtests from biotech universe catalog"
```

---

### Task 9: Add Local Universe Snapshot CLI

**Files:**

- Create: `scripts/build_biotech_universe_snapshot.py`
- Modify: `tests/test_bootstrap_research_snapshot.py`
- Create: `tests/test_build_biotech_universe_snapshot.py`

- [ ] **Step 1: Add failing CLI tests**

Create `tests/test_build_biotech_universe_snapshot.py`:

```python
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_build_biotech_universe_snapshot_help_runs_from_repo_root():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/build_biotech_universe_snapshot.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--xbi-holdings" in result.stdout
    assert "--ibb-holdings" in result.stdout
    assert "--exchange-listings" in result.stdout


def test_build_biotech_universe_snapshot_writes_duckdb_membership(tmp_path):
    from scripts.build_biotech_universe_snapshot import build_snapshot_from_csvs

    xbi = tmp_path / "xbi.csv"
    ibb = tmp_path / "ibb.csv"
    listings = tmp_path / "listings.csv"
    _write_csv(xbi, [{"ticker": "MRNA", "company_name": "Moderna, Inc.", "exchange": "NASDAQ", "asset_type": "common_stock", "source_weight": "0.01"}])
    _write_csv(ibb, [{"ticker": "JNJ", "company_name": "Johnson & Johnson", "exchange": "NYSE", "asset_type": "common_stock", "source_weight": "0.02"}])
    _write_csv(listings, [{"ticker": "XBI", "company_name": "SPDR S&P Biotech ETF", "exchange": "NYSEARCA", "asset_type": "etf", "industry": "ETF"}])
    db_path = tmp_path / "research.duckdb"

    result = build_snapshot_from_csvs(
        xbi_holdings=xbi,
        ibb_holdings=ibb,
        exchange_listings=listings,
        db_path=db_path,
        as_of_date="2026-05-08",
    )

    assert result["universe_id"] == "biotech_us_v1"
    assert result["member_count"] == 2
    assert result["benchmark_tickers"] == ["XBI"]

    import duckdb

    conn = duckdb.connect(str(db_path))
    members = conn.execute(
        "SELECT universe_id, ticker, membership_source FROM universe_membership ORDER BY ticker"
    ).fetchall()
    snapshot = conn.execute(
        "SELECT bias_status, survivorship_bias_warning, coverage_json FROM universe_snapshots"
    ).fetchone()
    conn.close()

    assert members == [
        ("biotech_us_v1", "JNJ", "ibb"),
        ("biotech_us_v1", "MRNA", "xbi"),
    ]
    assert snapshot[0] == "current_constituents_only"
    assert snapshot[1] is True
    assert json.loads(snapshot[2])["member_count"] == 2


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_build_biotech_universe_snapshot.py -q --basetemp .pytest_tmp\biotech-task9-fail
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Create CLI script**

Create `scripts/build_biotech_universe_snapshot.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database
from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot


def build_snapshot_from_csvs(
    *,
    xbi_holdings: str | Path,
    ibb_holdings: str | Path,
    exchange_listings: str | Path,
    db_path: str | Path | None = None,
    as_of_date: str,
) -> dict:
    rows = []
    rows.extend(_read_rows(Path(xbi_holdings), source="xbi"))
    rows.extend(_read_rows(Path(ibb_holdings), source="ibb"))
    rows.extend(_read_rows(Path(exchange_listings), source="exchange_listings"))
    snapshot = build_universe_snapshot(rows, as_of_date=as_of_date)
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    _write_snapshot(path, snapshot)
    return {
        "universe_snapshot_id": snapshot.universe_snapshot_id,
        "universe_id": snapshot.universe_id,
        "member_count": len(snapshot.members),
        "benchmark_tickers": list(snapshot.benchmark_tickers),
        "bias_status": snapshot.bias_status,
        "survivorship_bias_warning": snapshot.survivorship_bias_warning,
    }


def _read_rows(path: Path, *, source: str) -> list[UniverseSourceRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            UniverseSourceRow(
                ticker=row["ticker"],
                company_name=row["company_name"],
                exchange=row["exchange"],
                asset_type=row["asset_type"],
                source=source,
                source_weight=_optional_float(row.get("source_weight")),
                industry=row.get("industry"),
                cik=row.get("cik"),
                cusip=row.get("cusip"),
                isin=row.get("isin"),
            )
            for row in reader
        ]


def _write_snapshot(db_path: Path, snapshot) -> None:
    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        payload = snapshot.to_catalog_payload()
        conn.execute(
            """
            INSERT OR REPLACE INTO universe_snapshots (
                universe_snapshot_id,
                universe_id,
                as_of_date,
                bias_status,
                survivorship_bias_warning,
                member_count,
                benchmark_tickers_json,
                source_payload_json,
                coverage_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                payload["universe_snapshot_id"],
                payload["universe_id"],
                payload["as_of_date"],
                payload["bias_status"],
                payload["survivorship_bias_warning"],
                payload["member_count"],
                payload["benchmark_tickers_json"],
                payload["source_payload_json"],
                payload["coverage_json"],
            ],
        )
        for member in snapshot.members:
            conn.execute(
                """
                INSERT OR REPLACE INTO universe_membership (
                    universe_id,
                    security_id,
                    ticker,
                    member_from,
                    member_to,
                    weight,
                    membership_source,
                    as_of_date
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                [
                    snapshot.universe_id,
                    member.security_id,
                    member.ticker,
                    snapshot.as_of_date,
                    ",".join(member.source_memberships),
                    snapshot.as_of_date,
                ],
            )
    finally:
        conn.close()


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xbi-holdings", required=True)
    parser.add_argument("--ibb-holdings", required=True)
    parser.add_argument("--exchange-listings", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--db-path", default=str(RESEARCH_DB_PATH))
    args = parser.parse_args()
    result = build_snapshot_from_csvs(
        xbi_holdings=args.xbi_holdings,
        ibb_holdings=args.ibb_holdings,
        exchange_listings=args.exchange_listings,
        db_path=args.db_path,
        as_of_date=args.as_of_date,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run task tests**

Run:

```powershell
pytest tests/test_build_biotech_universe_snapshot.py -q --basetemp .pytest_tmp\biotech-task9
```

Expected: PASS.

- [ ] **Step 5: Commit Task 9**

Run:

```powershell
git add scripts\build_biotech_universe_snapshot.py tests\test_build_biotech_universe_snapshot.py
git commit -m "feat: add biotech universe snapshot cli"
```

---

### Task 10: Final Integration Verification

**Files:**

- Verify all files changed in Tasks 1-9.
- No new implementation files should remain untracked.

- [ ] **Step 1: Run focused Python suites**

Run:

```powershell
pytest tests/test_backtest_strategy_registry.py tests/test_backtest_data_sources.py tests/test_backtest_price_snapshot.py tests/test_tiingo_price_ingestion.py tests/test_fundamentals_ingestion.py tests/test_biotech_universe_builder.py tests/test_biotech_universe_loader.py tests/test_provider_rate_limit.py tests/test_provider_fetch_log.py tests/test_build_biotech_universe_snapshot.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py tests/test_kline_workspace_js.py tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp\biotech-integration
```

Expected: PASS.

- [ ] **Step 2: Build chart bundle**

Run:

```powershell
npm run build --prefix src\kline
```

Expected: PASS and no unstaged bundle drift after the build.

- [ ] **Step 3: Verify mock entrypoint removal**

Run:

```powershell
rg -n "Run Demo Universe|portfolio/demo/run" static src tests
```

Expected: no results.

- [ ] **Step 4: Verify survivorship and rate-limit guardrails exist**

Run:

```powershell
rg -n "current_constituents_only|survivorship_bias_warning|rate_limited|provider_fetch_log|FixedWindowRateLimit" src tests scripts
```

Expected: results in universe builder, portfolio output, provider log, rate-limit tests, and snapshot CLI.

- [ ] **Step 5: Confirm git status**

Run:

```powershell
git status --short --branch
```

Expected: clean working tree after all task commits.

- [ ] **Step 6: Handle final verification failures**

If Task 10 fails, return to the task that introduced the failing behavior,
apply the fix there, rerun that task's focused tests, and commit using that
task's commit command. Do not create a broad final commit from Task 10.

If Task 10 passes without changes, do not create an empty commit.
