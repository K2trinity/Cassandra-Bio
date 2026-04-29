# Kline Real Data + Backtest Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all K-line mock data with real sources, restructure the K-line page into a chart + multi-tab workspace, and complete the loop from event investigation to backtest execution.

**Architecture:** Keep Flask + Jinja as the page shell, reuse the existing React/D3 UMD chart bundle for visualization, and add thin Python services to normalize market data, event ingestion, and report-to-signal extraction. Persist all event data in `src/backtest/events_db.py`, cache OHLC via Parquet mtime, and persist backtest runs as JSON under `data/backtest_results/` so the UI can reload historical results.

**Tech Stack:** Flask, Flask-SocketIO, Jinja2, React 19 UMD bundle, D3, pandas, yfinance, SQLite, Gemini, pytest

---

## Scope Note

This spec touches four subsystems: market data, event ingestion, K-line UI restructuring, and backtest/report integration. Strictly speaking, it could be split into separate plans, but this document keeps a single execution plan because the user explicitly requested one plan based on the existing design. To keep that safe, the work is divided into four release gates:

1. Phase 1 ships real data with empty states.
2. Phase 2 ships the new page shell and tabbed workflow.
3. Phase 3 ships runnable backtests and chart overlays.
4. Phase 4 ships report-to-signal extraction and macro event ingestion.

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/services/market_data_service.py` | Wrap `src.backtest.data_loader` with 24h cache freshness and chart-ready row formatting |
| `src/services/event_ingestion_service.py` | Orchestrate openFDA, ClinicalTrials, and later GDELT ingestion with 6h fetch caching |
| `src/services/signal_extractor.py` | Extract structured trading events from completed report text via `GeminiClient` |
| `src/tools/gdelt_client.py` | Query and normalize biotech-relevant macro/geopolitical events |
| `tests/test_market_data_service.py` | Unit tests for OHLC freshness, refresh fallback, and empty-state behavior |
| `tests/test_event_ingestion_service.py` | Unit tests for source normalization, fetch-cache behavior, and DB writes |
| `tests/test_backtest_api.py` | Route-level tests for `/api/backtest/*` and persisted result loading |
| `tests/test_signal_extractor.py` | Unit tests for report event extraction and DB insertion behavior |
| `tests/test_gdelt_client.py` | Unit tests for macro event normalization |

### Modified Files

| File | Change |
|------|--------|
| `app.py` | Replace mock `/kline/<symbol>` payloads with service calls; add backtest and signal extraction routes |
| `templates/kline_report.html` | Convert to top/bottom layout, add tabs, events list, report tab, backtest tab, and tab-to-chart interactions |
| `src/backtest/data_loader.py` | Keep fetch/load helpers stable for service consumption; only adjust if tests expose formatting gaps |
| `src/backtest/events_db.py` | Add fetch-log helpers so empty API responses can still be cached for 6h |
| `src/backtest/signals.py` | Extend `EVENT_SCORE` with macro event weights |
| `src/backtest/runner.py` | Add single-run backtest entrypoint that returns metrics, equity curve, and CAR rows |
| `src/kline/chart/types.ts` | Extend chart types for macro event types, event source, and backtest overlay data |
| `src/kline/chart/CandlestickChart.tsx` | Render selected-event highlighting and backtest equity overlay with secondary axis |
| `src/kline/chart/index.tsx` | Pass new chart config fields through the UMD entry |
| `src/tools/openfda_client.py` | Add helpers that normalize approvals/recalls/adverse events into `biotech_events` rows |
| `src/tools/clinical_trials_client.py` | Add helpers that normalize trial milestones/results into `biotech_events` rows |
| `tests/test_kline_web_integration.py` | Update route/template tests for real data, tabs, and no-mock contract |

### Deferred on Purpose

| File | Reason |
|------|--------|
| `src/tools/gnews_client.py` | The design labels this as future iteration. Keep it out of the first execution cycle to preserve YAGNI. |

## Phase 1 Release Gate

Outcome: `/kline/<ticker>` uses real OHLC + real events only, and renders explicit empty states when sources return nothing.

### Task 1: Lock the Real-Data Route Contract

**Files:**
- Modify: `tests/test_kline_web_integration.py`
- Read: `app.py`
- Read: `templates/kline_report.html`

- [ ] **Step 1: Add a failing route test that monkeypatches future service calls**

Target assertions:
- `/kline/MRNA` returns `200`
- the route uses service-returned OHLC rows and events
- the rendered HTML no longer depends on inline mock-loop data generation

- [ ] **Step 2: Add a failing template assertion for the new three-tab shell**

Target strings:
- `data-tab="events"`
- `data-tab="report"`
- `data-tab="backtest"`

- [ ] **Step 3: Run the focused test file and confirm failure**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: failure because `market_data_service` and `event_ingestion_service` do not exist yet and the current template has no tab shell.

- [ ] **Step 4: Record the intended service interface in the test names**

Use these names consistently for the rest of the plan:

```python
get_ohlc_rows(ticker: str, max_age_hours: int = 24) -> list[dict]
get_events_for_ticker(ticker: str, max_age_hours: int = 6) -> list[dict]
```

- [ ] **Step 5: Do not change app code yet**

Keep this task test-only so the next tasks have a concrete red baseline.

### Task 2: Add `market_data_service` with 24h Freshness Logic

**Files:**
- Create: `src/services/market_data_service.py`
- Create: `tests/test_market_data_service.py`
- Read: `src/backtest/data_loader.py`

- [ ] **Step 1: Write a failing unit test for stale-cache refresh**

Test cases:
- cached Parquet newer than 24h -> service returns `load_ohlc()`
- cached Parquet older than 24h -> service calls `refresh_ohlc()`
- refresh returns empty -> service returns `[]`

- [ ] **Step 2: Run the new unit test and confirm failure**

Run: `pytest tests/test_market_data_service.py -q`

Expected: `ModuleNotFoundError` or missing function failure.

- [ ] **Step 3: Create the service with a single public function**

```python
def get_ohlc_rows(ticker: str, max_age_hours: int = 24) -> list[dict]:
    ...
```

Implementation rules:
- use Parquet file mtime to decide freshness
- call `load_ohlc()` for fresh cache
- call `refresh_ohlc()` for stale cache
- serialize `date` to `YYYY-MM-DD`
- return `[]` on failures or empty DataFrames

- [ ] **Step 4: Add a tiny private helper for path freshness**

Helper name:
- `_is_cache_stale(path: Path, max_age_hours: int) -> bool`

- [ ] **Step 5: Re-run the unit test until green**

Run: `pytest tests/test_market_data_service.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the service**

```bash
git add src/services/market_data_service.py tests/test_market_data_service.py
git commit -m "feat(kline): add market data service with 24h cache freshness"
```

### Task 3: Normalize Source Events from openFDA and ClinicalTrials

**Files:**
- Modify: `src/tools/openfda_client.py`
- Modify: `src/tools/clinical_trials_client.py`
- Create: `tests/test_event_ingestion_service.py`

- [ ] **Step 1: Write failing normalization tests for openFDA rows**

Cover:
- approval payload -> `type="fda_decision"`
- recall/safety payload -> `type="regulatory_change"` or `fda_decision` only if clearly approval-related
- `source="openfda"`
- required keys: `id`, `date`, `type`, `priority`, `ticker`, `catalyst`, `sentiment`, `source`

- [ ] **Step 2: Write failing normalization tests for ClinicalTrials rows**

Cover:
- completed/posted results -> `type="clinical_readout"`
- terminated/suspended/withdrawn -> negative sentiment
- `source="clinicaltrials"`

- [ ] **Step 3: Run the test file and confirm failure**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: helper functions do not exist yet.

- [ ] **Step 4: Add `normalize_biotech_events()` helper to `OpenFDAClient` or module-level helper**

Required output shape:

```python
{
    "id": "...",
    "date": "YYYY-MM-DD",
    "type": "fda_decision",
    "priority": 1,
    "ticker": "MRNA",
    "disease_area": "",
    "catalyst": "...",
    "sentiment": "positive",
    "price_impact": None,
    "source": "openfda",
}
```

- [ ] **Step 5: Add `normalize_biotech_events()` helper to `clinical_trials_client.py`**

Rules:
- use trial status and results availability to derive sentiment
- use `completion_date` or `results_first_posted` as event date fallback
- skip records with no usable date

- [ ] **Step 6: Re-run the normalization tests until green**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: normalization-only tests pass, ingestion-cache tests still pending or skipped.

- [ ] **Step 7: Commit the source normalization work**

```bash
git add src/tools/openfda_client.py src/tools/clinical_trials_client.py tests/test_event_ingestion_service.py
git commit -m "feat(events): normalize openfda and clinicaltrials payloads into biotech events"
```

### Task 4: Add Event Fetch-Log Storage and Ingestion Service

**Files:**
- Modify: `src/backtest/events_db.py`
- Create: `src/services/event_ingestion_service.py`
- Modify: `tests/test_event_ingestion_service.py`

- [ ] **Step 1: Add failing tests for 6h fetch caching, including empty-result caching**

Cover:
- first request fetches sources and writes DB
- second request within 6h does not hit external sources
- empty-source result still records a fetch timestamp so repeated visits stay cold for 6h

- [ ] **Step 2: Run the test file and confirm failure**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: missing fetch-log helpers and missing service module.

- [ ] **Step 3: Extend `events_db.py` with a small fetch-log table**

Add helpers:

```python
init_fetch_log_table() -> None
record_fetch_attempt(ticker: str, source: str, item_count: int) -> None
get_last_fetch_at(ticker: str, source: str) -> str | None
```

Reason: `biotech_events` alone cannot cache “real empty result” visits.

- [ ] **Step 4: Create `event_ingestion_service.py` with one public API**

```python
def get_events_for_ticker(ticker: str, max_age_hours: int = 6) -> list[dict]:
    ...
```

Internal behavior:
- initialize DB tables
- query openFDA and ClinicalTrials only if source fetch is stale
- normalize results
- `insert_events()` into `biotech_events`
- `record_fetch_attempt()` even when zero rows are returned
- return `get_events_for_chart(ticker)`

- [ ] **Step 5: Re-run the ingestion tests until green**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: cache-hit and empty-result tests pass.

- [ ] **Step 6: Smoke-test the DB helpers directly**

Run: `python -c "from src.backtest.events_db import init_db, init_fetch_log_table; init_db(); init_fetch_log_table(); print('OK')"`

Expected: `OK`

- [ ] **Step 7: Commit the ingestion layer**

```bash
git add src/backtest/events_db.py src/services/event_ingestion_service.py tests/test_event_ingestion_service.py
git commit -m "feat(events): add fetch-log cache and event ingestion service"
```

### Task 5: Replace Mock `/kline/<symbol>` Data with Service Calls

**Files:**
- Modify: `app.py`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Change `kline_view()` to call the new services**

Route behavior:
- `ohlc_rows = get_ohlc_rows(symbol.upper())`
- `events_list = get_events_for_ticker(symbol.upper())`
- never synthesize fallback candles or fake events

- [ ] **Step 2: Add route-level empty-state test coverage**

Cover:
- empty OHLC + empty events still renders page
- template receives `ohlc_json=[]` and `events_json=[]`

- [ ] **Step 3: Run the K-line integration tests**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: route tests pass, tab/layout tests still fail.

- [ ] **Step 4: Add a quick manual smoke check for the route payload**

Run: `python -c "from app import app; c = app.test_client(); r = c.get('/kline/MRNA'); print(r.status_code)"`

Expected: `200`

- [ ] **Step 5: Commit Phase 1 route integration**

```bash
git add app.py tests/test_kline_web_integration.py
git commit -m "feat(kline): serve real market and event data in kline route"
```

## Phase 2 Release Gate

Outcome: the page uses the new top/bottom workspace, supports Events / Report / Backtest tabs, and keeps the report flow working.

### Task 6: Extend Chart Types for Macro Events and Backtest Overlay

**Files:**
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/index.tsx`

- [ ] **Step 1: Add a failing TypeScript contract check**

Use a temporary compile check:

Run: `cd src/kline && npx tsc --noEmit chart/types.ts chart/index.tsx`

Expected: later this command should pass after the new types are added.

- [ ] **Step 2: Extend `BiotechEvent.type` with macro values**

Add:
- `geopolitical`
- `trade_policy`
- `sanctions`
- `regulatory_change`
- `macro_economic`

- [ ] **Step 3: Add `source` to `BiotechEvent`**

Use:
- `openfda | clinicaltrials | gdelt | cassandra_report | manual`

- [ ] **Step 4: Add backtest overlay types**

Add:

```ts
export interface EquityPoint { date: string; equity: number; }
highlightedEventId?: string;
equityCurve?: EquityPoint[];
```

- [ ] **Step 5: Pass the new props through `index.tsx`**

Update `window.PokieChart.render()` config forwarding only, no drawing logic yet.

- [ ] **Step 6: Re-run the TypeScript compile check**

Run: `cd src/kline && npx tsc --noEmit chart/types.ts chart/index.tsx`

Expected: no errors.

- [ ] **Step 7: Commit the chart type changes**

```bash
git add src/kline/chart/types.ts src/kline/chart/index.tsx
git commit -m "feat(kline): extend chart types for macro events and backtest overlay"
```

### Task 7: Add Selected-Event Highlighting and Equity Overlay to the Chart

**Files:**
- Modify: `src/kline/chart/CandlestickChart.tsx`

- [ ] **Step 1: Add a local compile check for the chart component**

Run: `cd src/kline && npx tsc --noEmit chart/CandlestickChart.tsx`

Expected: compile errors will guide prop changes.

- [ ] **Step 2: Add `highlightedEventId` support**

Behavior:
- if event ID matches the highlighted ID, draw a stronger glow/ring
- keep existing hover behavior intact

- [ ] **Step 3: Add optional `equityCurve` rendering**

Behavior:
- draw a semi-transparent orange line
- add a right Y-axis only when `equityCurve.length > 0`
- do not disturb candle scaling on the left axis

- [ ] **Step 4: Keep `onEventClick` behavior unchanged**

Do not rewrite marker hit-testing; only layer the highlight and overlay.

- [ ] **Step 5: Re-run the local compile check**

Run: `cd src/kline && npx tsc --noEmit chart/CandlestickChart.tsx`

Expected: no TypeScript errors.

- [ ] **Step 6: Rebuild the bundle only after TypeScript is green**

Run: `cd src/kline && npm run build`

Expected: updated `dist/` artifacts.

- [ ] **Step 7: Copy the bundle into `static/vendor/` if the project still tracks built assets**

Run:

```bash
cd src/kline
npm run build
Copy-Item dist/pokie-chart.umd.js ..\..\static\vendor\pokie-chart.umd.js -Force
if (Test-Path dist/style.css) { Copy-Item dist/style.css ..\..\static\vendor\pokie-chart.css -Force }
```

- [ ] **Step 8: Commit the chart overlay work**

```bash
git add src/kline/chart/CandlestickChart.tsx static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css
git commit -m "feat(kline): add selected event highlighting and equity overlay"
```

### Task 8: Convert `kline_report.html` to the Top/Bottom Multi-Tab Layout

**Files:**
- Modify: `templates/kline_report.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add failing template assertions for the new shell**

Assert presence of:
- top chart region
- bottom workspace panel
- tabs for `Events`, `Report`, `Backtest`
- resize/collapse handles

- [ ] **Step 2: Replace the 2-column grid with a top/bottom layout**

Required structure:
- top section about 65vh for chart
- bottom section about 35vh for workspace
- mobile fallback to stacked blocks

- [ ] **Step 3: Add the tab bar and tab panels**

Tab IDs:
- `events-tab`
- `report-tab`
- `backtest-tab`

- [ ] **Step 4: Preserve the existing overview button and report content container**

Keep these DOM anchors stable if possible:
- `overview-trigger`
- `report-content`

- [ ] **Step 5: Add the collapsible + resizable panel controls**

Minimum behavior:
- one collapse button
- one drag handle on the panel edge
- no persistence yet

- [ ] **Step 6: Re-run the template integration test**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: layout assertions pass, event/report/backtest interaction tests still pending.

- [ ] **Step 7: Commit the shell conversion**

```bash
git add templates/kline_report.html tests/test_kline_web_integration.py
git commit -m "feat(kline): convert kline report page to top-bottom tabbed workspace"
```

### Task 9: Wire Events and Report Tab Interactions

**Files:**
- Modify: `templates/kline_report.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add a rendered Events tab list using `eventsData`**

Each card should show:
- date
- type badge
- catalyst summary
- sentiment
- source badge
- `Investigate` button

- [ ] **Step 2: Add simple client-side filters**

Filters:
- event type
- source
- start/end date

Keep filtering in plain browser-side JS for MVP.

- [ ] **Step 3: Wire chart marker click -> expand panel -> switch to Events tab -> scroll to matching card**

Use:
- `data-event-id="<event id>"`
- `element.scrollIntoView({ block: 'center' })`

- [ ] **Step 4: Wire event card click -> set `highlightedEventId` and redraw chart**

Use the UMD chart config and local page state; do not add a new server endpoint.

- [ ] **Step 5: Wire `Investigate` button -> switch to Report tab -> queue the event-specific analysis**

Keep using the existing `/api/analyze` flow and Socket.IO progress events.

- [ ] **Step 6: Re-run the K-line integration tests**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: event/report bridge tests pass.

- [ ] **Step 7: Commit the interaction wiring**

```bash
git add templates/kline_report.html tests/test_kline_web_integration.py
git commit -m "feat(kline): wire events tab interactions into report workflow"
```

## Phase 3 Release Gate

Outcome: the Backtest tab can run a single-ticker backtest for the current chart window, show persisted results, and overlay the equity curve on the chart.

### Task 10: Add Single-Run Backtest API Tests and Runner Entry Points

**Files:**
- Create: `tests/test_backtest_api.py`
- Modify: `src/backtest/runner.py`

- [ ] **Step 1: Add failing tests for `POST /api/backtest/run`**

Request contract:

```json
{
  "ticker": "MRNA",
  "start_date": "2025-01-01",
  "end_date": "2025-03-31",
  "stop_loss_pct": -0.08,
  "max_position_pct": 0.2,
  "slippage_pct": 0.001
}
```

Expected response keys:
- `run_id`
- `metrics`
- `equity_curve`
- `event_car`

- [ ] **Step 2: Add failing tests for `GET /api/backtest/results/<run_id>`**

Cover:
- existing run returns `200`
- unknown run returns `404`

- [ ] **Step 3: Run the route tests and confirm failure**

Run: `pytest tests/test_backtest_api.py -q`

Expected: routes and helper functions do not exist yet.

- [ ] **Step 4: Add a focused runner API without breaking `run_walk_forward()`**

Add to `runner.py`:

```python
run_kline_backtest(...)
load_saved_run(run_id: str) -> dict | None
```

Rules:
- use existing `generate_signals()`, `apply_strategy()`, `compute_metrics()`, `compute_event_car()`
- save each result as `data/backtest_results/<run_id>.json`

- [ ] **Step 5: Keep `run_walk_forward()` unchanged except for internal reuse if convenient**

Do not refactor the research runner unless needed by the tests.

- [ ] **Step 6: Re-run the backtest API test file**

Run: `pytest tests/test_backtest_api.py -q`

Expected: runner-level tests may pass once the app routes are added in the next task.

### Task 11: Add Backtest Routes to `app.py`

**Files:**
- Modify: `app.py`
- Modify: `tests/test_backtest_api.py`

- [ ] **Step 1: Implement `POST /api/backtest/run`**

Validation rules:
- require `ticker`, `start_date`, `end_date`
- use defaults for risk controls if omitted
- return `400` on invalid date range

- [ ] **Step 2: Implement `GET /api/backtest/results/<run_id>`**

Use `load_saved_run()` and return `404` when the file is absent.

- [ ] **Step 3: Keep response shape flat and chart-ready**

Top-level response fields:
- `run_id`
- `metrics`
- `equity_curve`
- `event_car`
- `ticker`
- `start_date`
- `end_date`

- [ ] **Step 4: Re-run the backtest route tests**

Run: `pytest tests/test_backtest_api.py -q`

Expected: all route tests pass.

- [ ] **Step 5: Smoke-test the routes manually**

Run: `python -c "from app import app; c = app.test_client(); print(c.get('/api/backtest/results/not-found').status_code)"`

Expected: `404`

- [ ] **Step 6: Commit the backtest API layer**

```bash
git add app.py src/backtest/runner.py tests/test_backtest_api.py
git commit -m "feat(backtest): add single-run backtest routes and result persistence"
```

### Task 12: Build the Backtest Tab UI and Chart Overlay Wiring

**Files:**
- Modify: `templates/kline_report.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add the Backtest form controls**

Required inputs:
- date range
- stop loss
- max position
- slippage
- `Run Backtest` button

- [ ] **Step 2: Add a loading + empty state region**

States:
- no run yet
- running
- loaded results
- API error

- [ ] **Step 3: On submit, call `POST /api/backtest/run`**

Client behavior:
- disable button while running
- render returned metrics cards
- render CAR table
- pass `equity_curve` into the chart renderer

- [ ] **Step 4: Add historical result reload support**

When `run_id` is present in local page state, keep a helper that can call `GET /api/backtest/results/<run_id>` to rehydrate on refresh later.

- [ ] **Step 5: Add the report-to-backtest CTA shell**

After report completion, show:
- `Extract Signals → Backtest`

For now the button can switch tabs and queue extraction in Phase 4.

- [ ] **Step 6: Re-run the K-line integration tests**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: template tests pass with Backtest tab DOM present.

- [ ] **Step 7: Commit the Backtest tab**

```bash
git add templates/kline_report.html tests/test_kline_web_integration.py
git commit -m "feat(kline): add backtest tab and equity overlay wiring"
```

## Phase 4 Release Gate

Outcome: completed reports can emit structured events back into `biotech_events`, macro events can be ingested, and signal weights cover the new event taxonomy.

### Task 13: Add Report-to-Event Signal Extraction

**Files:**
- Create: `src/services/signal_extractor.py`
- Create: `tests/test_signal_extractor.py`
- Modify: `app.py`

- [ ] **Step 1: Add failing extraction tests against a mocked Gemini client**

Cover:
- valid JSON response -> list of normalized events
- invalid/empty response -> `[]`
- inserted rows use `source="cassandra_report"`

- [ ] **Step 2: Run the unit test and confirm failure**

Run: `pytest tests/test_signal_extractor.py -q`

Expected: missing module or helper failure.

- [ ] **Step 3: Create the extractor with one public function**

```python
def extract_report_events(report_text: str, ticker: str) -> list[dict]:
    ...
```

Implementation rules:
- call `create_report_client().generate_json(...)`
- normalize `event_type`, `sentiment`, `priority`, `catalyst`, `estimated_impact`, `date`
- map output to `biotech_events` rows

- [ ] **Step 4: Add an app route for the button bridge**

Add:
- `POST /api/backtest/extract-signals`

Request:
- `ticker`
- `report_text`

Response:
- `inserted_count`
- `events`

Reason: the UI needs an explicit action when the user clicks `Extract Signals → Backtest`.

- [ ] **Step 5: Re-run the signal extractor tests**

Run: `pytest tests/test_signal_extractor.py -q`

Expected: all extraction tests pass.

- [ ] **Step 6: Commit the report signal bridge**

```bash
git add src/services/signal_extractor.py app.py tests/test_signal_extractor.py
git commit -m "feat(backtest): extract report signals into biotech events"
```

### Task 14: Add GDELT Macro Ingestion and Extend Signal Weights

**Files:**
- Create: `src/tools/gdelt_client.py`
- Create: `tests/test_gdelt_client.py`
- Modify: `src/services/event_ingestion_service.py`
- Modify: `src/backtest/signals.py`
- Modify: `src/kline/chart/types.ts`

- [ ] **Step 1: Add failing tests for GDELT event normalization**

Cover:
- trade-policy article -> `trade_policy`
- sanctions article -> `sanctions`
- generic macro biotech context -> `macro_economic` or `geopolitical`

- [ ] **Step 2: Add failing tests for new `EVENT_SCORE` weights**

Assert:
- `geopolitical = 0.3`
- `trade_policy = 0.3`
- `sanctions = 0.4`
- `regulatory_change = 0.4`
- `macro_economic = 0.2`

- [ ] **Step 3: Run the focused tests and confirm failure**

Run: `pytest tests/test_gdelt_client.py tests/test_event_ingestion_service.py -q`

Expected: missing client and missing macro source logic.

- [ ] **Step 4: Implement `gdelt_client.py` normalization**

Public helper:

```python
def fetch_biotech_macro_events(query: str, max_records: int = 20) -> list[dict]:
    ...
```

Rules:
- normalize to `biotech_events` rows
- set `source="gdelt"`
- drop records with no usable date or summary

- [ ] **Step 5: Extend `event_ingestion_service.py` to optionally include GDELT**

MVP rule:
- include GDELT in Phase 4 only
- keep the same 6h fetch-cache logic as other sources

- [ ] **Step 6: Extend `signals.py` and `types.ts` together**

Keep taxonomy aligned across:
- ingestion
- chart union types
- signal scoring

- [ ] **Step 7: Re-run the focused tests until green**

Run: `pytest tests/test_gdelt_client.py tests/test_event_ingestion_service.py -q`

Expected: all macro ingestion and scoring tests pass.

- [ ] **Step 8: Commit the macro event layer**

```bash
git add src/tools/gdelt_client.py src/services/event_ingestion_service.py src/backtest/signals.py src/kline/chart/types.ts tests/test_gdelt_client.py tests/test_event_ingestion_service.py
git commit -m "feat(events): add gdelt macro ingestion and macro signal weights"
```

### Task 15: Final Verification Pass

**Files:**
- No new files required unless fixes are discovered

- [ ] **Step 1: Run all targeted K-line and backtest tests**

Run:

```bash
pytest tests/test_kline_web_integration.py tests/test_market_data_service.py tests/test_event_ingestion_service.py tests/test_backtest_api.py tests/test_signal_extractor.py tests/test_gdelt_client.py -q
```

Expected: all pass.

- [ ] **Step 2: Run a chart bundle build**

Run: `cd src/kline && npm run build`

Expected: successful bundle build with updated UMD artifact.

- [ ] **Step 3: Run a Flask route smoke test**

Run:

```bash
python -c "from app import app; c = app.test_client(); print(c.get('/kline/MRNA').status_code); print(c.get('/api/status').status_code)"
```

Expected: `200` then `200`

- [ ] **Step 4: Run a backtest API smoke test with monkeypatched runner if network data is unavailable**

Goal:
- verify route wiring even when real yfinance/GDELT are unavailable in CI or offline environments.

- [ ] **Step 5: If any verification fails, fix immediately and rerun only the failing subset**

Do not mark the plan complete until the rerun is green.

- [ ] **Step 6: Commit final fixes if needed**

```bash
git add -A
git commit -m "test: verify kline real-data and backtest closed loop"
```

## Spec Coverage Check

- Section 1.1 Stock Price: Tasks 2 and 5
- Section 1.2 Catalyst Events: Tasks 3, 4, and 5
- Section 1.3 Geopolitical / Macro Events: Task 14
- Section 1.4 Daily News: intentionally deferred, matching the design doc
- Section 2 Page Layout: Tasks 8 and 9
- Section 3 Tabs: Tasks 8, 9, and 12
- Section 4 LLM Bridge: Task 13
- Section 5 Schema / Type / Weight Extensions: Tasks 4, 6, and 14
- Section 6 New Files: covered by the new-file table above
- Section 7 Modified Files: covered by the modified-file table above
- Section 8 Phased Delivery: reflected directly in the four release gates

## Placeholder Scan

No placeholder markers or vague future-work phrases remain in the executable path. The only intentionally deferred item is `src/tools/gnews_client.py`, because the source spec explicitly marks it as a future iteration.

## Type Consistency Check

Use these names consistently during implementation:

- `get_ohlc_rows`
- `get_events_for_ticker`
- `run_kline_backtest`
- `load_saved_run`
- `extract_report_events`
- `fetch_biotech_macro_events`
- `highlightedEventId`
- `equityCurve`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-kline-real-data-backtest-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
