# Kline Phase 2.2 Daily Zoom, Event Density, and Strategy Framework Design

## Context

Phase 2.1 tightened the Kline data truth boundary. That improved backtest input quality, but it exposed three usability and modeling problems:

1. Chart event particles became too sparse because the visual layer now reads the same strict trusted projection used by backtests.
2. The Kline chart supports range selection for context, but selecting a range does not actually zoom or pan the daily candlestick view.
3. The backtest strategy framework is still a simple score threshold plus same-day execution model, so it cannot answer whether a catalyst class has durable signal, how signal decays after an event, or how market regime affects execution.

The next phase should not loosen the data truth boundary. It should split visual observability from trading eligibility, add daily-level chart navigation, and introduce a small event-window strategy framework that remains easy to test.

## Decision

Phase 2.2 will implement a **Daily Research Loop**:

1. Daily candlestick zoom and pan become first-class chart behavior.
2. Event particles are displayed in tiers so chart density returns without contaminating backtests.
3. Backtests move from a single hard-coded signal threshold to an event-window strategy model with explicit features, holding periods, execution choices, and diagnostics.

The hard rule is:

> Backtest inputs remain strict trusted events. Chart particles may show additional visual-only candidates, but every non-trading particle must be visually distinct and must be excluded from backtest execution.

## Goals

1. Let users zoom and pan the daily Kline chart without introducing minute or hourly data.
2. Restore useful event-particle density for research while preserving the trusted backtest boundary.
3. Make particle trust, ownership, confidence, and trading eligibility visible in hover and detail views.
4. Add fixed daily range controls such as `3M`, `6M`, `1Y`, `2Y`, and `All`.
5. Make brush selection optionally zoom into the selected daily date window instead of only fetching context.
6. Introduce an extensible backtest framework with feature building, signal modeling, strategy execution, and diagnostics.
7. Keep the first upgraded strategy deterministic, explainable, and covered by focused tests.
8. Avoid broad refactors outside the Kline chart, Kline workspace event projection, and backtest modules.

## Non-Goals

- Do not add minute-level or hourly-level candlestick data.
- Do not relax the trusted-event rules for backtest inputs.
- Do not make quarantined events appear as normal chart particles.
- Do not train an ML model in this phase.
- Do not redesign the full workspace UI.
- Do not replace the existing D3/canvas chart stack.
- Do not require paid market data or paid news APIs.

## Architecture

### 1. Daily Chart Viewport

Add a chart viewport model that stores the active daily date window independently from the full price series.

The viewport should include:

- `fullStart`: first available daily candle date.
- `fullEnd`: last available daily candle date.
- `visibleStart`: first visible daily candle date.
- `visibleEnd`: last visible daily candle date.
- `minVisibleDays`: minimum window size, initially 20 trading days.
- `source`: one of `initial`, `preset`, `brush`, `wheel`, `pan`, or `reset`.

The chart keeps daily candles as the only data grain. Zooming changes which dates are visible; it does not request lower-granularity candles.

Expected interactions:

- Preset buttons set the viewport to the last `3M`, `6M`, `1Y`, `2Y`, or full available range.
- Brush selection with at least `minVisibleDays` zooms to the selected date range.
- Brush selection below `minVisibleDays` expands symmetrically until the minimum is met.
- Reset returns to `fullStart` through `fullEnd`.
- Wheel zoom changes `visibleStart` and `visibleEnd` around the cursor date.
- Horizontal drag pans the visible daily window without leaving the full available range.

The existing context-range query can continue to use the selected range, but zoom state must not depend on backend context fetch success.

### 2. Event Display Tiers

Introduce a visual event-tier projection for chart rendering. It sits above the raw event store and below the chart renderer.

The chart should receive event objects with an explicit `display_tier`:

- `tradable`: trusted, scoped, no quarantine reason, and backtest eligible.
- `trusted_context`: trusted and useful for chart interpretation, but not backtest eligible.
- `visual_candidate`: not backtest eligible, but useful as a visual clue because it has a date, source, title, confidence, and no hard quarantine reason.
- `audit_hidden`: quarantined, legacy untrusted, rejected, missing date, or missing source identity. Hidden by default.

Default display:

- Show `tradable`, `trusted_context`, and `visual_candidate`.
- Hide `audit_hidden`.
- Allow a developer or audit toggle to show hidden rows later, but that toggle is not required for the first implementation.

Visual encoding:

- `tradable`: solid particle with normal opacity.
- `trusted_context`: solid particle with lighter opacity.
- `visual_candidate`: hollow or ring particle with lower opacity.
- `audit_hidden`: gray or muted styling when explicitly enabled later.

The event detail panel and hover tooltip should expose:

- `display_tier`
- `trust_status`
- `ownership_status`
- `confidence`
- `backtest_eligible`
- `source`
- `source_url` when available
- `source_run_id`
- `query_hash`
- `quarantine_reason` when present

### 3. Event Density Control

Particle density should be managed visually, not by deleting or silently filtering valid visual events.

Daily density behavior:

- Multiple events on the same date are vertically offset inside a stable event lane.
- If the same date has more particles than can fit cleanly, the chart renders a compact cluster marker with a count.
- Hovering a cluster shows the ordered event list for that date.
- Cluster ordering prioritizes `tradable`, then `trusted_context`, then `visual_candidate`, then higher confidence, then newer source timestamp.

This keeps the chart readable while still allowing the user to see when a date has many relevant events.

### 4. Kline Workspace Event Projection

The workspace service should expose two related projections:

- Strict backtest projection: only `tradable` events.
- Chart display projection: all visible display tiers except hidden audit rows.

The strict projection remains the only input to strategy execution.

The chart display projection should be deterministic and should not rely on frontend string heuristics. The service layer should calculate `display_tier` from trust fields, ownership fields, event metadata, confidence, and quarantine status, then send it to the frontend.

Recommended tier rules:

- `tradable` when `trust_status = trusted`, `backtest_eligible = true`, `quarantine_reason` is empty, `schema_version >= 2`, and `ownership_status` is `owned`, `market_relevant`, or `macro_context`.
- `trusted_context` when `trust_status = trusted`, `backtest_eligible` is false, `quarantine_reason` is empty, and the event has a valid date and source.
- `visual_candidate` when the event has a valid date, source, title, confidence, and no quarantine reason, but does not satisfy strict trust or backtest eligibility.
- `audit_hidden` for quarantine, rejected, legacy untrusted, missing date, missing source, or explicit quarantine reason.

Legacy untrusted rows remain hidden by default. If a legacy row is valuable, it should be repaired or re-ingested into a trusted schema rather than silently promoted.

### 5. Event-Window Backtest Framework

Introduce a small framework under `src/backtest` that separates features, signals, execution, and diagnostics.

The core units:

- `EventFeatureBuilder`: builds a per-event feature table from trusted events and daily OHLCV data.
- `EventWindowSignalModel`: converts event features into dated signal intents.
- `EventWindowStrategyExecutor`: turns signal intents into trades and daily positions.
- `BacktestDiagnostics`: explains results by event type, source, confidence bucket, holding period, and market regime.

The first implementation should remain deterministic and configuration-driven.

Initial strategy configuration:

- `entry_mode`: `next_open` by default.
- `holding_days`: default `3`.
- `max_position_pct`: existing configured limit remains supported.
- `stop_loss_pct`: existing stop behavior remains supported.
- `take_profit_pct`: optional, disabled by default.
- `event_decay`: default linear decay across the holding window.
- `confidence_weighting`: enabled by default.
- `regime_filter`: optional, disabled by default until structured macro coverage is stable.
- `slippage_bps`: existing basic slippage stays available.

Initial event feature fields:

- `event_id`
- `event_date`
- `event_type`
- `category`
- `source`
- `confidence`
- `impact_score`
- `direction_hint`
- `trust_status`
- `ownership_status`
- `backtest_eligible`
- `pre_event_return_5d`
- `pre_event_return_20d`
- `realized_gap_1d`
- `realized_return_3d`
- `realized_return_5d`
- `volatility_20d`
- `volume_ratio_20d`

Initial signal fields:

- `signal_date`
- `event_id`
- `direction`
- `strength`
- `decay_day`
- `holding_days`
- `entry_mode`
- `reason`

Initial trade attribution fields:

- `trade_id`
- `event_id`
- `entry_date`
- `exit_date`
- `entry_price`
- `exit_price`
- `position_pct`
- `gross_return`
- `net_return`
- `exit_reason`
- `signal_strength`
- `source`
- `category`
- `confidence`

### 6. Strategy Diagnostics

Backtest output should include enough structure to explain whether a strategy worked.

Add diagnostics for:

- Total return, annualized return, volatility, max drawdown, win rate, and average trade return.
- Buy-and-hold benchmark for the same ticker.
- Optional XBI/SPY benchmark when those price series are available.
- Returns by event category.
- Returns by source.
- Returns by confidence bucket: low, medium, high.
- Returns by holding day.
- Signal decay table showing realized return by day offset from event date.
- Top positive and negative event-attributed trades.

The Kline workspace can initially render only a subset, but the saved backtest payload should include the full diagnostics object.

### 7. Frontend Surface

The frontend changes should be scoped to the existing Kline workspace and chart bundle.

Chart controls:

- Add compact daily range buttons: `3M`, `6M`, `1Y`, `2Y`, `All`.
- Add reset zoom icon button.
- Keep chart controls work-focused and compact.
- Do not add a landing-style explanation panel.

Chart behavior:

- Brush selection updates the viewport.
- Tooltip respects zoomed coordinates.
- Event particles and trade markers render only if their dates fall inside the visible viewport.
- Clusters and same-day offsets keep layout stable.

Details behavior:

- Event detail rows show tier and trust provenance.
- Backtest detail rows show event attribution when a trade is event-driven.

### 8. Data Flow

The intended flow:

1. Source ingestion writes raw and trusted event fields.
2. Workspace service builds chart display events with `display_tier`.
3. Workspace API returns daily candles, display events, source status, and latest backtest summary.
4. Chart state initializes viewport from full candle dates.
5. User zooms or pans daily viewport locally.
6. Chart renders candles, volume, event particles, clusters, and trade overlays for visible dates.
7. Backtest endpoint reads strict trusted events only.
8. Backtest framework builds event features, signal intents, trades, positions, equity curve, and diagnostics.
9. Saved backtest payload returns to the workspace with event attribution.

### 9. Error Handling

Viewport:

- If candle data is empty, show the existing empty chart state and do not render zoom controls as active.
- If a preset range is longer than available history, clamp to the full range.
- If a wheel or pan action would leave the available range, clamp to `fullStart` and `fullEnd`.

Event tiers:

- Missing date or missing source always maps to `audit_hidden`.
- Missing confidence maps to a neutral confidence value for sorting, but should remain visible only if the tier rules otherwise allow it.
- Quarantine reason always wins over visual candidate rules.

Backtest:

- If no tradable events exist, return a successful no-trade result with diagnostics explaining `no_tradable_events`.
- If price data is missing around an event window, skip that event and record a diagnostic skip reason.
- If entry or exit prices cannot be resolved, skip the trade intent and record a diagnostic skip reason.

## Testing Strategy

### Unit Tests

Add focused tests for:

- Viewport clamping and preset range calculations.
- Brush-to-zoom minimum day expansion.
- Wheel zoom around a cursor date.
- Pan clamping.
- Event tier classification.
- Same-day event ordering and cluster summarization.
- Event feature table generation.
- Event-window signal generation.
- Strategy execution with fixed holding periods.
- No-trade backtest response when trusted events are absent.
- Trade attribution fields in saved result payloads.

### Integration Tests

Add or extend integration tests for:

- Workspace API returns display tiers while backtest uses strict events.
- Kline static bundle exposes zoom controls and tier fields.
- Running a Kline backtest saves diagnostics and event-attributed trades.
- Existing Phase 2.1 trust-boundary tests continue passing.

### Manual Checks

Use a ticker with known event density, such as `MRNA`, to verify:

- Particles are denser than strict trusted-only mode.
- Tradable and visual-only particles are visually distinct.
- Zooming to `3M`, `6M`, `1Y`, `2Y`, and `All` works on daily candles.
- Drag selection zooms into the selected daily range.
- Reset restores the full daily chart.
- Backtest result does not include visual-only events as trade triggers.

## Rollout Plan

Implement in this order:

1. Daily viewport and zoom controls.
2. Event display tier projection in the service layer.
3. Frontend particle tier styling and same-day clustering.
4. Event-window backtest feature builder and signal model.
5. Strategy executor and diagnostics.
6. Workspace and saved-run payload integration.

This order fixes the immediate UX blocker first, then restores chart observability, then improves the modeling framework.

## Acceptance Criteria

The phase is complete when:

1. A daily Kline chart can zoom, pan, and reset without requesting minute or hourly candles.
2. The default chart displays `tradable`, `trusted_context`, and `visual_candidate` particles with distinct styling.
3. Hidden audit events do not appear by default.
4. Event detail and tooltip surfaces expose tier and trust provenance.
5. Backtests only use `tradable` events.
6. Backtest outputs include event features, signal intents, attributed trades, equity curve, and diagnostics.
7. Existing Phase 2.1 trust-boundary regression tests still pass.
8. New viewport, tier, and event-window strategy tests pass.

## Spec Self-Review

- Placeholder scan: no unresolved placeholder text remains.
- Internal consistency: chart display tiers are broader than backtest eligibility, while backtest inputs remain strict.
- Scope check: this is one phase with three dependent slices; daily zoom and event display tiers improve the research surface before the strategy framework consumes strict events.
- Ambiguity check: daily zoom means changing the visible date window only; it does not add minute or hourly candles.
