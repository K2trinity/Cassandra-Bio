# Cassandra Kline: Real Data Integration + Backtest Closed Loop

## Overview

Migrate PokieTicker Kline capabilities into Cassandra with real data sources, replacing all mock data. Restructure the Kline page layout for better UX, add multi-tab functionality (Events / Report / Backtest), and create a closed loop: Investigation → Kline → Backtest.

Target users: biomedical researchers who use Cassandra for disease/drug research surveys. Kline + backtest is an added-value capability, not the primary workflow.

## Guiding Principle

**No mock data anywhere.** If a data source is unavailable or empty, show the real empty state. Never generate fake data to fill gaps.

---

## 1. Data Sources

### 1.1 Stock Price (OHLC)

**Source:** yfinance (free, already used in `src/backtest/data_loader.py`)

**Integration:**
- New `src/services/market_data_service.py` wraps `data_loader.fetch_ohlc()` / `load_ohlc()`
- Adds cache expiry: if Parquet file is older than 1 day, auto-refresh
- Kline route calls `market_data_service.get_ohlc(ticker)` instead of generating mock data
- Returns empty list + appropriate UI empty state if yfinance fails

### 1.2 Catalyst Events (Priority 1)

**Sources:**
- openFDA API → FDA approvals, recalls, adverse events (extend existing `src/tools/openfda_client.py`)
- ClinicalTrials.gov API → trial results, phase changes (extend existing `src/tools/clinical_trials_client.py`)

**Integration:**
- Both sources write to `events_db.py` → `biotech_events` table
- Reuse existing schema; `source` field set to `openfda` or `clinicaltrials`
- New `src/services/event_ingestion_service.py` orchestrates fetching from both sources for a given ticker
- Trigger: on-demand when user visits `/kline/<ticker>`, with cache — if events for this ticker were fetched within the last 6 hours, skip re-fetch. No background scheduler needed for MVP.

### 1.3 Geopolitical / Macro Events (Priority 2)

**Source:** GDELT Project (free, updates every 15 minutes, covers sanctions, trade policy, diplomatic events)

**Integration:**
- New `src/tools/gdelt_client.py`
- Query GDELT GKG (Global Knowledge Graph) for events matching biomedical/pharma/trade themes
- Write to `biotech_events` table with extended type values
- `source` field: `gdelt`

### 1.4 Daily News (Priority 3, future iteration)

**Source:** GNews free tier (100 requests/day, 12-hour delay, 30-day history)

**Integration:**
- New `src/tools/gnews_client.py` (deferred to Phase 4)
- Supplementary news flow, not blocking MVP

### 1.5 Data Flow

```
yfinance ──→ market_data_service ──→ Parquet cache ──→ Kline route ──→ frontend
openFDA ──┐
ClinTrials ─┤──→ event_ingestion_service ──→ events_db (biotech_events) ──→ Kline route ──→ frontend
GDELT ────┘
```

---

## 2. Page Layout

### 2.1 Navigation

Left sidebar unchanged: Cassandra Logo / New Investigation / K-Line / Report / Settings.

### 2.2 Kline Page Structure (top-bottom split)

**Top section (~65% viewport height):**
- Ticker info bar: symbol, current price, daily change
- K-line chart: full width, D3-based (existing pokie-chart)
- Event markers overlaid on candlesticks
- Backtest equity curve overlaid as semi-transparent line on secondary Y-axis

**Bottom section (~35% viewport height):**
- Resizable: drag top edge to adjust height
- Collapsible: can minimize to a thin bar, auto-expands on event click
- Tab bar with three tabs: Events | Report | Backtest

### 2.3 Interaction Flow

1. K-line event marker click → panel expands → Events tab scrolls to corresponding event
2. Events tab "Investigate" button → switches to Report tab, triggers investigation workflow
3. Report complete → "Extract Signals → Backtest" button appears → switches to Backtest tab
4. All three tabs independently accessible, no forced sequence

---

## 3. Tab Specifications

### 3.1 Events Tab

- Chronological event timeline for current ticker
- Each event card: date, type badge, catalyst summary, sentiment indicator, source badge
- Click event card → highlight corresponding marker on K-line chart
- "Investigate" button on each event card → triggers investigation for that event context
- Filter controls: by event type, by date range, by source

### 3.2 Report Tab

- Migrated from current right-side report panel (existing `kline_report.html` functionality)
- Preserves: overview investigation button, Socket.IO progress updates, analysis_complete/report_queued protocol
- Addition: after report completes, show "Extract Signals → Backtest" button at bottom
- Report content display unchanged

### 3.3 Backtest Tab

**Parameter controls:**
- Date range picker (start/end)
- Strategy parameters: stop loss % (slider, default -8%), max position % (slider, default 20%), slippage % (input, default 0.1%)
- "Run Backtest" button

**Results display:**
- Equity curve rendered on K-line chart (semi-transparent orange line, right Y-axis)
- Metric cards: Sharpe ratio, annualized return, max drawdown, win rate, profit factor
- Event CAR table: which events were predictive, t-stat significance

**Backend:**
- `POST /api/backtest/run` — accepts `{ticker, start_date, end_date, stop_loss_pct, max_position_pct, slippage_pct}`
- Returns `{run_id, metrics, equity_curve, event_car}`
- `GET /api/backtest/results/<run_id>` — retrieve historical results
- Calls existing `runner.py` → `run_single_ticker()`

---

## 4. LLM Bridge: Report → Backtest Signals

### 4.1 Signal Extraction

New `src/services/signal_extractor.py`:
- Input: completed investigation report text
- LLM call (Gemini via existing `src/llms/gemini_client.py`) with structured extraction prompt
- Output per event detected:
  ```json
  {
    "event_type": "fda_decision | clinical_readout | partnership | ...",
    "sentiment": "positive | negative | neutral",
    "priority": 1-3,
    "catalyst": "one-line summary",
    "estimated_impact": "high | medium | low",
    "date": "YYYY-MM-DD"
  }
  ```
- Extracted events written to `biotech_events` table with `source: cassandra_report`

### 4.2 Backtest Consumption

Existing `signals.py` → `generate_signals()` already consumes events from `events_db`. No changes needed to backtest logic — extracted signals automatically flow into backtest via the shared event table.

---

## 5. Schema Extensions

### 5.1 biotech_events.type — new values

Existing: `fda_decision`, `clinical_readout`, `partnership`, `financing`, `patent`, `competitor`

New: `geopolitical`, `trade_policy`, `sanctions`, `regulatory_change`, `macro_economic`

### 5.2 signals.py EVENT_SCORE — new weights

```python
# Macro events: lower weight than direct catalysts
"geopolitical": 0.3,
"trade_policy": 0.3,
"sanctions": 0.4,
"regulatory_change": 0.4,
"macro_economic": 0.2,
```

### 5.3 biotech_events.source — expected values

`openfda`, `clinicaltrials`, `gdelt`, `gnews`, `cassandra_report`, `manual`

---

## 6. New Files

| File | Purpose |
|------|---------|
| `src/services/market_data_service.py` | OHLC fetch + cache with expiry |
| `src/services/event_ingestion_service.py` | Orchestrate event fetching from all sources |
| `src/services/signal_extractor.py` | LLM extraction: report → structured events |
| `src/tools/gdelt_client.py` | GDELT API client |
| `src/tools/gnews_client.py` | GNews API client (Phase 4) |

## 7. Modified Files

| File | Changes |
|------|---------|
| `app.py` (kline route) | Replace mock data with `market_data_service` + `events_db` calls |
| `app.py` (new routes) | Add `/api/backtest/run`, `/api/backtest/results/<run_id>` |
| `templates/kline_report.html` | Top-bottom layout, multi-tab panel, backtest UI |
| `src/backtest/events_db.py` | No schema change needed (type/source are TEXT fields) |
| `src/backtest/signals.py` | Extend `EVENT_SCORE` dict with macro event types |
| `src/kline/chart/types.ts` | Extend `BiotechEvent.type` union with new event types |

---

## 8. Phased Delivery

### Phase 1 — MVP: Real Data (no mock)
- `market_data_service.py` replaces mock OHLC in kline route
- `event_ingestion_service.py` fetches from openFDA + ClinicalTrials.gov
- Kline route reads real data; empty state shown when data unavailable

### Phase 2 — Page Restructure
- Top-bottom layout conversion
- Multi-tab panel (Events + Report migration)
- Event marker click ↔ panel interaction
- Resizable/collapsible panel

### Phase 3 — Backtest Closed Loop
- Backtest tab UI (parameters + results)
- `/api/backtest/run` and `/api/backtest/results` endpoints
- Equity curve overlay on K-line chart
- Metric cards + event CAR table

### Phase 4 — LLM Bridge + Macro Events
- `signal_extractor.py` (Report → event signals)
- GDELT client + ingestion
- GNews client (if free tier sufficient)
- "Extract Signals → Backtest" button wiring
