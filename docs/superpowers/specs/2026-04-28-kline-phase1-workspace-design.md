# Kline Phase 1 Workspace Design

## Decision

Phase 1 will build a Cassandra-specific biotech catalyst K-line workspace. It
will not implement PokieTicker's general news layer, similar-news workflow,
forecast panel, or AI range attribution. It will, however, create stable
interfaces for those Phase 2 and Phase 3 layers.

The implementation must improve structure rather than add more code to the
current large files. Kline should become the first modular vertical slice in
the project.

## Current State

The existing Kline feature has useful pieces, but they are not organized as a
complete workspace:

- `/kline` and `/kline/<symbol>` routes exist.
- The React/D3 candlestick bundle renders candles, catalyst markers, hover,
  range selection, and backtest overlays.
- OHLC loading, event ingestion, and backtest APIs exist.
- The visible page has Events and Backtest panels.

The major gaps are:

- The page has no obvious ticker selector or company identity bar.
- Local OHLC cache currently only contains `MRNA.parquet`; other tickers depend
  on live Yahoo Finance fetches and can fail due to rate limits.
- ClinicalTrials normalization can assign events to sponsor fragments such as
  `ModernaTX,`, `National`, or `University` instead of the requested ticker.
- `app.py` is over 2700 lines and mixes unrelated concerns.
- `templates/kline_report.html` is over 1300 lines and mixes CSS, markup,
  browser state, event rendering, chart calls, and backtest calls.
- `templates/kline.html`, `templates/kline_report.html`, chart partials, and
  loader assets create overlapping Kline surfaces.

## Scope

Phase 1 includes:

- A clear ticker selector and search flow.
- Company identity and OHLC status in the first viewport.
- A biotech catalyst layer using FDA, ClinicalTrials, GDELT, and
  Cassandra-extracted report events when available.
- Correct ticker attribution for catalyst events.
- A workspace layout with chart, catalyst timeline, selected event details,
  backtest, and source status.
- A modular Kline backend boundary.
- Data and UI contracts that allow Phase 2 and Phase 3 to add layers without
  rewriting Phase 1.
- Cleanup of obsolete Kline-specific templates, loaders, and inline logic once
  the new path is active.

Phase 1 excludes:

- General market news ingestion.
- Similar-news and similar-day workflows.
- Forecast and prediction panels.
- AI range attribution.
- Full-project refactoring outside Kline.

## Architecture

Kline will be split into a self-contained vertical slice:

```text
Flask app
  -> registers Kline blueprint

Kline routes
  -> KlineWorkspaceService
      -> TickerResolver
      -> OHLCProvider
      -> CatalystEventProvider
      -> BacktestResultProvider
      -> LayerRegistry
  -> KlineWorkspacePayload
  -> Kline workspace template and static assets
  -> PokieChart-compatible chart component
```

Recommended files:

```text
src/kline/
  models.py
  routes.py
  ticker_resolver.py
  workspace_service.py
  providers/
    __init__.py
    ohlc_provider.py
    catalyst_provider.py
    backtest_provider.py

templates/
  kline_workspace.html

static/kline/
  workspace.css
  workspace.js
```

`app.py` should register the Kline blueprint and stop owning Kline route
implementation. Kline-specific business logic should not remain in `app.py`.

## Public URL Compatibility

Existing public URLs remain valid:

```text
GET  /kline
GET  /kline/<symbol>
POST /api/backtest/run
GET  /api/backtest/results/<run_id>
```

New Kline-specific APIs may be added:

```text
GET /api/kline/workspace/<symbol>
GET /api/kline/tickers
GET /api/kline/events/<symbol>
GET /api/kline/range-context/<symbol>?start=YYYY-MM-DD&end=YYYY-MM-DD
```

`/api/kline/range-context` is a Phase 1 interface for selected ranges. In
Phase 1 it returns OHLC movement and catalyst summaries only. Phase 3 can use
the same contract for AI attribution.

## Data Model

### Ticker Ownership

The model separates requested ticker, company identity, and source entity:

```text
requested_ticker: MRNA
company_identity: Moderna, Inc.
source_entity: ModernaTX, Inc. or another sponsor/entity found in source data
```

The requested ticker is the chart ownership key. Source names, sponsors, drug
names, brand names, NCT IDs, and FDA application numbers are metadata. They
must not overwrite ticker ownership.

### KlineWorkspacePayload

```typescript
interface KlineWorkspacePayload {
  ticker: string;
  company: KlineCompany;
  price: KlinePriceSeries;
  layers: KlineLayer[];
  panels: KlinePanelState;
  data_status: KlineDataStatus[];
  warnings: KlineWarning[];
  capabilities: KlineCapability[];
}
```

Responsibilities:

- `ticker`: normalized symbol.
- `company`: company name, aliases, sector, and known biotech universe status.
- `price`: OHLC rows, date range, last close, cache status, last updated.
- `layers`: chart layers. Phase 1 uses candles, catalysts, and backtest.
- `panels`: default panel state and last-run metadata.
- `data_status`: per-source readiness and failures.
- `warnings`: user-visible warnings such as rate limits or stale cache.
- `capabilities`: available features and disabled future capabilities.

### KlineEvent

```typescript
interface KlineEvent {
  id: string;
  ticker: string;
  date: string;
  type: string;
  category: "clinical" | "regulatory" | "corporate" | "macro" | "report";
  title: string;
  summary: string;
  sentiment: "positive" | "negative" | "neutral" | "unknown";
  priority: 1 | 2 | 3;
  impact_score?: number;
  confidence: "high" | "medium" | "low";
  source: string;
  source_url?: string;
  source_ids?: string[];
  source_entity?: string;
  disease_area?: string;
  drug_name?: string;
  metadata: Record<string, unknown>;
}
```

Rules:

- `ticker` is always the requested chart ticker.
- `source_entity` stores sponsor, organization, brand, or source-side company.
- `source_ids` stores identifiers such as NCT IDs, FDA application numbers, or
  stable article IDs.
- `confidence` affects display and source warnings.
- `metadata` is for extensibility; stable fields should not be hidden there.

### KlineLayer

```typescript
interface KlineLayer {
  id: string;
  kind:
    | "candles"
    | "catalysts"
    | "backtest"
    | "news"
    | "macro"
    | "forecast"
    | "range_analysis";
  label: string;
  visible_by_default: boolean;
  status: "ready" | "empty" | "loading" | "error" | "disabled";
  points?: KlineEvent[];
  series?: unknown[];
  summary?: KlineLayerSummary;
  error?: string;
}
```

Phase 1 implements:

- `candles`: OHLC price data.
- `catalysts`: biotech catalyst events.
- `backtest`: backtest equity curve, signals, and trades after a run.

Phase 2 can add:

- `news`: general news particles.
- `macro`: sector, ETF, and macro context.

Phase 3 can add:

- `range_analysis`: AI explanation of selected ranges.
- `similar_events`: similar historical days or event patterns.

### KlineDataStatus

```typescript
interface KlineDataStatus {
  source: "ohlc" | "openfda" | "clinicaltrials" | "gdelt" | "backtest" | "news";
  status: "ready" | "empty" | "stale" | "rate_limited" | "error" | "disabled";
  item_count: number;
  last_fetch_at?: string;
  message?: string;
}
```

This model distinguishes empty data from failure:

- `ready`: data available.
- `empty`: request completed but returned no rows.
- `stale`: cached data exists but is old.
- `rate_limited`: external source refused or throttled.
- `error`: request, parsing, or database failure.
- `disabled`: future capability is intentionally unavailable.

## Event Attribution

ClinicalTrials and openFDA normalizers should not guess ticker ownership from
sponsor or brand text. They may create source-level candidates, but the
Kline catalyst provider wraps those candidates with the requested ticker:

```text
search_trials("MRNA")
  -> candidate sponsor="ModernaTX, Inc."
  -> KlineEvent ticker="MRNA", source_entity="ModernaTX, Inc."
```

The same rule applies to openFDA. Brand names, generic names, sponsor names,
and drug labels become metadata, not ticker values.

Existing database rows do not need an immediate destructive migration. Phase 1
should fix new workspace attribution and may add targeted tests for the
requested-ticker ownership rule. If existing bad rows need cleanup, that should
be handled by a separate maintenance script.

## Workspace UI

The Phase 1 workspace uses a chart-first layout with a working side panel.

```text
Kline Topbar
  - current ticker dropdown
  - ticker/company search
  - quick biotech universe
  - source status summary

Company/OHLC Header
  - company name and ticker
  - last close
  - OHLC date range
  - cache freshness
  - hover OHLC readout
  - warnings chip

Main Workspace
  - left: candlestick chart
  - chart overlay: catalyst particles, selected event highlight, backtest overlay
  - chart layer controls: Candles, Catalysts, Backtest
  - future disabled capabilities: News, Macro, Forecast
  - right: Catalysts, Details, Backtest, Status
```

Mobile layout can stack chart and panels vertically.

### Ticker Selector

The selector includes:

- Current ticker button.
- Recommended biotech universe.
- Search input for symbol or company name.
- Recent tickers stored locally.
- Error state for invalid symbols.

The user should not need to edit the URL to change ticker.

### Company and Price Status

The header shows:

- Company name and ticker.
- Last close.
- OHLC coverage range.
- Cache freshness.
- Data-source warnings.

This prevents the current ambiguous experience where the chart can look like an
unknown company.

### Catalyst Particles

Phase 1 particles represent biotech catalysts only:

- `clinical`: clinical trials, readouts, result posts, terminations.
- `regulatory`: FDA, labels, approvals, recalls, safety signals.
- `corporate`: partnerships, financing, patents, M&A when available.
- `macro`: GDELT biotech macro context with lower confidence.
- `report`: Cassandra report-extracted events when available.

Display rules:

- Particle size reflects priority or impact score.
- Color reflects category or sentiment.
- Opacity reflects confidence.
- Hover shows title, source, date, confidence, and source entity.
- Click locks the event and opens Details.
- Clicking an event card highlights the particle.

### Right Panel

Tabs:

- `Catalysts`: timeline with type, source, date, sentiment, and filters.
- `Details`: selected event metadata and source identifiers.
- `Backtest`: existing backtest controls and results.
- `Status`: data-source status and warnings.

### Range Selection

Phase 1 preserves range selection but does not implement AI attribution:

- Selected range shows start date, end date, price change, and catalyst count.
- The range can filter visible catalysts.
- `KlineRangeContext` is generated for Phase 3.
- No fake "Ask AI" behavior is shown in Phase 1.

## Cleanup Rules

Phase 1 must reduce Kline complexity instead of creating parallel systems.

Rules:

- Kline routes move out of `app.py`.
- Kline business logic moves out of `app.py`.
- Large inline CSS and JS move out of `templates/kline_report.html`.
- New Kline workspace replaces the old Kline entry.
- Duplicate Kline templates, chart partials, and loader assets should be
  deleted or clearly retired once unused.
- No long-term compatibility shims remain after Phase 1.
- Existing public URLs stay compatible.

Expected cleanup candidates:

- `templates/kline.html` old report-triggering page.
- `templates/kline_report.html` old inline workspace, once replaced.
- `templates/partials/kline_chart_assets.html`, if no longer referenced.
- `templates/partials/kline_chart_runtime.html`, if no longer referenced.
- `static/vendor/pokie-chart-loader.js`, if no longer referenced.

The final implementation should verify no dead Kline references remain:

```text
rg "kline_report|kline_chart_loader|pokie-chart-loader|request_report|analysis_complete" templates static src tests
```

## Legacy Refactor Boundary

Kline is the first modular vertical slice. Phase 1 may refactor Kline-related
code because that is required for the feature quality. Phase 1 should not
refactor unrelated report, graph, PDF, config, or Socket.IO systems unless
needed to register the Kline blueprint.

Recommended future slices:

- Report routes and report file APIs.
- Graph routes and graph data APIs.
- Analysis task queue and Socket.IO handlers.
- Config and test endpoints.

Each slice should keep URL compatibility and add tests before removing old
paths.

## Testing Strategy

### Backend Unit Tests

Ticker resolver:

- Valid ticker normalization.
- Invalid ticker rejection.
- Known biotech universe company identity.

OHLC provider:

- Fresh cache.
- Stale cache.
- Missing cache.
- Empty data.
- Rate limit or external fetch error.
- `KlineDataStatus` generation.

Catalyst provider:

- Requested ticker is preserved for ClinicalTrials results.
- Sponsor and organization become `source_entity`.
- openFDA brand or drug name does not overwrite ticker.
- GDELT failures do not block FDA or ClinicalTrials events.
- Empty source responses produce source status instead of hard failure.

Workspace service:

- Payload contains ticker, company, price, layers, statuses, warnings, and
  capabilities.
- OHLC empty with catalysts still returns a valid payload.
- Catalysts empty with OHLC still returns a valid payload.
- Disabled Phase 2/3 capabilities do not render fake behavior.

Backtest:

- Existing validation remains.
- Existing public API URLs remain compatible after route migration.

### Template and Route Contract Tests

- `/kline/<symbol>` renders the new workspace.
- The page contains ticker selector, source status, layer controls, and panel
  tabs.
- The page does not contain the old report investigation flow.
- The page consumes workspace payload as the primary data contract.
- Old loader and partials are not referenced after cleanup.

### Chart Bundle Tests

- `KlineLayer` and `KlineEvent` contracts compile.
- Catalyst layer maps to chart markers.
- Selected event highlight works.
- Backtest overlay still receives equity curve, signals, and trades.

### Verification Commands

Focused backend:

```powershell
pytest tests/test_kline_web_integration.py -q
pytest tests/test_event_ingestion_service.py -q
pytest tests/test_market_data_service.py -q
pytest tests/test_kline_backtest_runner.py -q
```

Frontend bundle:

```powershell
cd src/kline
npm run build
```

## Acceptance Criteria

Phase 1 is complete when:

- Users can change tickers from the page.
- The first viewport identifies the company, ticker, price range, and data
  status.
- Biotech catalyst particles are attributed to the current ticker.
- ClinicalTrials and FDA source entities are retained as metadata.
- Empty, stale, rate-limited, and failed sources are visible to users.
- Chart, catalyst timeline, selected event details, backtest, and status form a
  coherent workspace.
- Phase 2 and Phase 3 interfaces exist as contracts but do not display fake
  functionality.
- `app.py` no longer owns Kline business implementation.
- Obsolete Kline templates, loader files, and inline report-triggering logic are
  removed or retired.
- Existing public Kline URLs and backtest URLs remain compatible.
