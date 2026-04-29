# Kline Phase 2 Multisource Events Design

Date: 2026-04-29

## Purpose

Phase 2 upgrades the Kline module from a phase1 catalyst workspace into a
biotech event intelligence surface. The priority order is:

1. Data depth.
2. Backtest depth.
3. Event particle visualization.

The product rule is: use multiple data sources, but never let unfiltered source
noise flow directly into the chart or backtest. The Kline chart can show a
broader event set when confidence is visible. The backtest must default to a
smaller high-confidence eligible event set.

## Current State

The existing phase1 code has a stable workspace boundary:

- `src/kline/workspace_service.py` builds candles, catalysts, and backtest
  layers.
- `src/services/event_ingestion_service.py` fetches openFDA, ClinicalTrials,
  and GDELT.
- `src/backtest/runner.py` returns metrics, equity curve, event CAR, signals,
  and trades.
- `src/kline/chart/CandlestickChart.tsx` already draws canvas event particles.

The main gaps are:

- News and macro remain disabled future capabilities in
  `src/kline/models.py`.
- ClinicalTrials normalization emits only coarse `clinical_readout` events,
  based mainly on `results_first_posted` or `completion_date`.
- Local historical event rows still contain old ticker attribution pollution
  such as sponsor or institution fragments used as tickers.
- GDELT is used as a macro source but is noisy and has shown error/rate-limit
  statuses locally.
- The chart draws particles, but the workspace passes only one catalyst layer.
- Backtest signal generation uses static event type weights and sentiment only;
  it has no source-tier attribution, confidence gating, benchmark context, or
  source/type diagnostics.

## Phase 2 Architecture

Phase 2 uses a ranked ingestion funnel:

```text
External sources
  -> source-specific clients and normalizers
  -> EventCandidate rows
  -> entity ownership gate
  -> biotech taxonomy gate
  -> duplicate clustering key
  -> confidence and impact scores
  -> KlineEvent records
  -> Kline layers and backtest eligible event set
```

The implementation keeps the existing SQLite event store and Kline dataclass
contracts. It extends event metadata rather than introducing a separate evidence
warehouse in this phase.

## Data Sources

### Tier 1: Official Biotech Event Backbone

ClinicalTrials.gov remains the primary clinical event source. Phase 2 extracts
multiple milestone event candidates from each retained trial:

- `trial_results_posted` from `results_first_posted`.
- `trial_primary_completion` from `primary_completion_date`.
- `trial_completion` from `completion_date`.
- `trial_status_change` from `last_update_posted` when the status is active or
  recruiting.
- `trial_termination` from `completion_date` or `last_update_posted` when the
  status is `TERMINATED`, `SUSPENDED`, or `WITHDRAWN`.

ClinicalTrials events preserve:

- Requested ticker as event ownership.
- Sponsor and collaborators as source attribution.
- NCT ID in `source_ids`.
- Phase, status, intervention, condition, `has_results`, and `why_stopped` in
  metadata.

openFDA remains the primary regulatory and safety source. Phase 2 keeps the
current approval and regulatory change support and prepares event taxonomy names
for:

- `fda_approval`.
- `fda_label_update`.
- `fda_recall`.
- `safety_signal`.

### Tier 2: Market News Main Source

Alpha Vantage `NEWS_SENTIMENT` is the phase2 market-news source. It is optional
and controlled by `ALPHA_VANTAGE_API_KEY`.

The client queries ticker-level market news with life-sciences-oriented topics
and normalizes articles into event candidates:

- `market_news` for general ticker news.
- `partnership_mna` for merger, acquisition, partnership, licensing, or deal
  terms.
- `earnings_financing` for earnings, offering, financing, debt, or cash runway
  terms.
- `analyst_news` for analyst rating, target, downgrade, or upgrade terms.

The client must not fail Kline when the API key is missing. Missing key returns
an empty source status with a message indicating that the source is disabled.

### Tier 3: Macro And Broad Web Supplement

GDELT remains a macro and broad web supplement. It does not become the primary
news source. GDELT events default to lower confidence unless a high-confidence
entity match exists or another source supports the same event cluster.

GDELT events are visible on the chart but are not backtest eligible by default
unless they pass the high-confidence threshold.

## Event Candidate Contract

Phase 2 stores scored candidate attributes in the existing event metadata. A
candidate normalizer should produce or preserve these stable fields:

```text
id
date
type
category
ticker
disease_area
catalyst
sentiment
source
source_entity
source_url
source_ids
confidence
metadata
```

The metadata should include:

```text
source_tier: official | market_news | macro | report
confidence_score: 0.0-1.0
impact_score: 0.0-1.0
backtest_eligible: true | false
dedupe_key: stable string
raw_type: source-side event type
entity_match: ticker | alias | sponsor | drug | unknown
supporting_sources: list of source names when clustered
```

Stable top-level fields remain authoritative. Metadata is for phase2 scoring,
filtering, and diagnostics.

## Entity Ownership And Noise Gates

Ticker ownership remains the requested chart ticker. Source-side sponsor,
organization, drug, brand, article source, and NCT IDs are attribution metadata.

An event candidate can pass the entity ownership gate when at least one of these
is true:

- The source query was ticker-scoped and the source returned ticker-specific
  metadata.
- The source text matches a company alias from `TickerResolver`.
- The source text matches a known source entity or sponsor for that ticker.
- The source text matches a known drug/product alias for that ticker.
- The event has a source identifier already tied to the requested ticker in the
  current event store.

Candidates that only mention a broad disease area or generic biomedical term do
not become ticker-owned events. They may appear as macro context only.

## Taxonomy

Phase 2 event types:

```text
trial_results_posted
trial_primary_completion
trial_completion
trial_status_change
trial_termination
clinical_readout
fda_approval
fda_label_update
fda_recall
safety_signal
market_news
analyst_news
partnership_mna
earnings_financing
macro_policy
geopolitical
trade_policy
sanctions
macro_economic
cassandra_report
```

Categories:

```text
clinical
regulatory
corporate
news
macro
report
```

## Scoring

Each event receives:

- `confidence_score`: how likely the event is real, relevant, and owned by the
  requested ticker.
- `impact_score`: how likely the event should move price.
- `priority`: display priority, with lower numbers more important.
- `backtest_eligible`: whether the event is included in the default strategy
  signal set.

Default backtest eligibility:

- Official clinical and regulatory events are eligible when
  `confidence_score >= 0.70`.
- Alpha Vantage news is eligible when `confidence_score >= 0.75` and
  `impact_score >= 0.45`.
- GDELT macro events are visible by default but not backtest eligible unless
  `confidence_score >= 0.85` and `impact_score >= 0.55`.

The chart can render events with `confidence_score >= 0.35` if their layer is
enabled, but low-confidence events should be visibly dimmer and clearly labeled.

## Deduplication

Phase 2 uses stable `dedupe_key` values to avoid flooding:

- ClinicalTrials: `ticker|source|event_type|nct_id|date`.
- openFDA: `ticker|source|event_type|application_or_recall_id|date`.
- Alpha Vantage: `ticker|source|normalized_title_or_url|date`.
- GDELT: `ticker|source|normalized_url_or_title|date`.

Events with the same dedupe key are inserted once. If a later candidate has a
higher confidence score or supporting source metadata, it can update metadata in
a future phase. Phase 2 may keep `INSERT OR IGNORE` for storage as long as
normalizers create stable IDs and the user-visible event count is deduped.

## Kline Workspace Layers

Phase 2 layers:

```text
candles
catalysts
news
macro
backtest
```

`catalysts` includes clinical, regulatory, corporate, and report events.

`news` includes Alpha Vantage market-news events.

`macro` includes GDELT macro and broad-web events.

Layer controls must allow users to toggle `catalysts`, `news`, `macro`, and
`backtest` independently. Event panels can show all active event layers, with
source/type/confidence metadata visible.

## Particle Visualization

The existing React canvas particle layer remains the renderer. Phase 2 improves
input and controls:

- Particle color follows category.
- Particle size follows impact score and priority.
- Opacity follows confidence score.
- Same-day clusters stack with capped density.
- Hover tooltip shows title, type, source, confidence score, impact score, and
  backtest eligibility.
- Clicking an event opens the Details panel.

This design does not require a new chart engine.

## Backtest Depth

The backtest runner should default to eligible events only. It returns the
current fields plus phase2 diagnostics:

```json
{
  "event_filter": {
    "input_events": 42,
    "eligible_events": 18,
    "excluded_events": 24,
    "min_confidence_score": 0.7
  },
  "event_attribution": {
    "by_source": [],
    "by_category": [],
    "by_type": []
  },
  "signal_summary": {
    "active_signal_days": 7,
    "long_signal_days": 5,
    "short_signal_days": 2,
    "mean_signal_strength": 0.24
  },
  "baseline": {
    "buy_hold_return": 0.12,
    "strategy_return": 0.07,
    "excess_return": -0.05
  }
}
```

The frontend should display these diagnostics in the Backtest panel. The chart
continues to render equity curve, signals, and trades.

## Error Handling

- Missing `ALPHA_VANTAGE_API_KEY` records `alphavantage` as disabled/empty and
  does not fail Kline.
- Source request failures produce source statuses and warnings.
- A failed optional source never blocks OHLC, official catalysts, or backtest.
- Backtest can run with zero eligible events and should report that no signals
  were generated.

## Testing Strategy

Backend tests:

- Alpha Vantage client normalizes ticker news into `market_news` events.
- Missing Alpha Vantage API key is non-fatal and returns an explicit status.
- ClinicalTrials milestone extraction emits multiple event types when dates are
  present.
- Event scoring marks official clinical/regulatory events as more trustworthy
  than macro events.
- Event filtering excludes low-confidence events from default backtest signals.
- Workspace service emits `news` and `macro` layers.
- Backtest response includes event filter, attribution, signal summary, and
  baseline diagnostics.

Frontend/static tests:

- Workspace JavaScript toggles `news` and `macro` event layers.
- Details panel shows confidence/impact/backtest eligibility when present.
- Backtest panel renders diagnostics from the runner payload.
- TypeScript chart build still succeeds.

## Acceptance Criteria

Phase 2 is complete when:

- Kline can ingest Alpha Vantage news when `ALPHA_VANTAGE_API_KEY` is set.
- Missing Alpha Vantage credentials produce an explicit source status, not a
  route failure.
- ClinicalTrials events are expanded beyond a single coarse readout event.
- Events carry `confidence_score`, `impact_score`, `source_tier`,
  `backtest_eligible`, and `dedupe_key` metadata.
- Kline workspace has separate `catalysts`, `news`, and `macro` event layers.
- Users can toggle event layers independently.
- Backtest defaults to eligible events and reports how many were included or
  excluded.
- Backtest returns source/category/type attribution and buy-hold baseline
  context.
- Existing phase1 Kline routes and APIs remain compatible.
- Existing tests plus phase2 focused tests pass.
