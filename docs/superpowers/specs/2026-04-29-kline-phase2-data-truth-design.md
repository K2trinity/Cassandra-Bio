# Kline Phase 2.1 Data Truth Boundary Design

## Context

The current Kline implementation has useful pieces in place, but the trust boundary is not strong enough for biotech trading workflows.

- `src/services/event_ingestion_service.py` fetches `openfda`, `clinicaltrials`, `alphavantage`, and `gdelt`, then returns `get_events_for_chart(ticker)`.
- `src/backtest/events_db.py` stores events in `data/events.db` with `INSERT OR IGNORE`, but legacy rows have no explicit trust, query provenance, source run, or ticker-scope fields.
- Local `data/events.db` contains old rows that can still appear in the Kline workspace even when the latest source status is `empty`, `disabled`, `rate_limited`, or `error`.
- Some historical `MRNA` rows appear to be generic RNA/mRNA title matches rather than Moderna-owned assets or trials.
- `src/kline/providers/backtest_provider.py` always returns `None`, so saved backtest runs are not loaded into the workspace.
- `/api/backtest/run` exists, but it reads raw events for the ticker and depends on a simple event-score threshold model.
- Macro is currently GDELT-only, broad-query, and fragile under rate limits; there is no structured market-regime layer.
- The chart has canvas event dots and hover glow, but it does not yet distinguish trusted, stale, quarantined, and source-failed states in a way that prevents visual overconfidence.

## Decision

Phase 2.1 will use a **Data Truth Boundary**. Kline, backtest, and chart layers must read trusted event projections, not raw cached rows.

The hard rule is:

> Any cached row must be scoped by ticker, source, source run, query identity, company identity, ownership status, schema version, and trust status before it can affect the Kline workspace, chart layers, or backtest.

## Goals

1. Prevent stale, legacy, test, or mis-scoped event rows from appearing in the wrong ticker workspace.
2. Prevent generic RNA/mRNA keyword matches from being treated as Moderna-owned clinical catalysts.
3. Separate source freshness status from event trust status.
4. Keep raw cache data for audit, but exclude untrusted rows from Kline and backtest by default.
5. Make backtests use only trusted, backtest-eligible events.
6. Add a real saved-run index so the Kline workspace can load the latest backtest for a ticker.
7. Add a structured macro layer that does not rely only on GDELT article search.
8. Keep UI event particles honest: default chart particles represent trusted events only; source and trust metadata must be visible in details.

## Non-Goals

- Do not physically delete `data/events.db` rows as the default fix.
- Do not build a full institutional event-driven strategy engine in this phase.
- Do not require paid news APIs to make the workspace usable.
- Do not make quarantined events visible in the production chart by default.
- Do not add broad refactors outside Kline, event ingestion, macro providers, and backtest persistence.

## Architecture

### 1. Event Trust Model

Add explicit trust/provenance fields to event storage and normalized event payloads:

- `ticker_scope`: canonical ticker whose workspace may use the event.
- `source`: upstream source such as `clinicaltrials`, `openfda`, `alphavantage`, `gdelt`, `macro_regime`.
- `source_run_id`: generated per source fetch attempt.
- `query_hash`: stable hash of the effective upstream query and source parameters.
- `company_identity`: canonical company identity used for matching, for example `MRNA|Moderna, Inc.`.
- `ownership_status`: one of `owned`, `market_relevant`, `macro_context`, `unowned`, `unknown`.
- `trust_status`: one of `trusted`, `quarantined`, `legacy_untrusted`, `rejected`.
- `schema_version`: integer event schema version. Phase 2.1 writes version `2`.
- `quarantine_reason`: short reason for non-trusted rows.

Legacy rows without schema version or trust fields are treated as `legacy_untrusted` at read time and excluded from trusted projections.

### 2. Trusted Event Repository

Introduce a repository boundary that replaces direct Kline/backtest reads from raw `biotech_events`:

- `get_trusted_events_for_chart(ticker)` returns only rows where:
  - `ticker_scope = ticker`
  - `trust_status = trusted`
  - `schema_version >= 2`
  - `ownership_status` is `owned`, `market_relevant`, or `macro_context`
- `get_trusted_events_for_backtest(ticker, start_date, end_date)` additionally requires:
  - event date in range
  - `metadata.backtest_eligible = true`
  - no `quarantine_reason`
- Raw read functions remain for audit and tests, but production Kline paths do not use them.

### 3. Source Freshness Versus Event Trust

Source fetch status and event trust are separate:

- `fetch_log` records source status: `ready`, `empty`, `disabled`, `rate_limited`, `error`, or `stale`.
- A failed source refresh must not mark old trusted events as fresh.
- Existing trusted events from the same ticker and source may still be displayed as historical events, but their source chip must show the latest source status.
- Empty or failed source fetches must not cause legacy or untrusted raw rows to appear.
- Cache freshness controls whether a source is queried again; trust controls whether a row can be consumed.

### 4. Clinical Ownership Gate

ClinicalTrials events are trusted only when ownership evidence passes:

- Primary sponsor or collaborator matches the resolved ticker company name or aliases.
- Known subsidiary aliases are allowed through `TickerResolver`.
- Generic tokens such as `RNA`, `mRNA`, disease terms, investigator names, academic sites, or trial title keywords do not establish ownership.
- Non-owned trials may be stored as `quarantined` with `ownership_status = unowned`, but they cannot appear in Kline or backtest.
- The event details panel may later expose quarantine reasons in a developer/debug view, but that is not enabled by default in this phase.

### 5. News and Macro Trust

News and macro are lower-trust by nature, so they require explicit classification:

- Alpha Vantage news rows are `market_relevant` only when ticker relevance metadata matches the requested ticker above the configured threshold.
- GDELT rows are `market_relevant` or `macro_context`, never `owned`.
- GDELT rows require source URL and date; otherwise they are quarantined.
- A new structured macro-regime provider produces `macro_context` events from market instruments and optional macro APIs:
  - Always available without API keys: `XBI`, `IBB`, `SPY`, `TLT`, `^VIX` OHLC-derived risk regime signals.
  - Optional with environment configuration: FRED-style rates/inflation series when an API key is present.
- Structured macro events use source `macro_regime`, not `gdelt`, so the chart can distinguish market regime from news-derived macro articles.

### 6. Backtest Persistence and Inputs

Backtest integration changes from "run-only" to "workspace-visible":

- `run_kline_backtest()` reads `get_trusted_events_for_backtest()`, not raw events.
- Backtest payload includes:
  - `event_filter`
  - `event_attribution`
  - `trust_summary`
  - `source_status_at_run`
  - `input_event_ids`
- Saving a run updates `data/backtest_results/index.json` with latest run metadata by ticker.
- `BacktestResultProvider.load_last_run(ticker)` reads the index, validates the run id, loads the JSON payload, and returns it to the workspace.
- The workspace backtest layer becomes `ready` when a valid saved run exists for the ticker.

### 7. UI and Chart Behavior

The default chart renders trusted events only.

- Catalyst, news, and macro layers are derived from trusted event metadata.
- Event details show `trust_status`, `ownership_status`, `source_run_id`, `query_hash`, `source_tier`, confidence score, impact score, and backtest eligibility.
- Source chips show latest source status separately from event counts.
- If a source is disabled, rate-limited, empty, or error, the chip says so even when historical trusted events exist.
- Event particles remain visible only for trusted events. Quarantined rows are excluded from chart particles and backtest overlays.

### 8. Operational Cleanup

Phase 2.1 includes a safe quarantine/rebuild path:

- Add a development command or service function to mark legacy rows as `legacy_untrusted`.
- Add a rebuild path that can refresh a ticker from sources and write schema version 2 events.
- Do not delete raw rows unless a separate explicit purge function is called.
- Tests must use temporary databases and must not mutate the developer's real `data/events.db`.

## Data Flow

1. Kline route asks `KlineWorkspaceService` for a ticker workspace.
2. `CatalystEventProvider` calls event ingestion/repository boundary.
3. Event ingestion refreshes stale sources by source, writes rows with trust/provenance metadata, and records fetch status.
4. Repository returns only trusted rows scoped to the requested ticker.
5. Workspace splits trusted rows into catalysts, news, and macro layers.
6. Backtest route runs against trusted backtest-eligible rows only.
7. Backtest save updates both payload JSON and latest-run index.
8. Workspace loads latest saved run through `BacktestResultProvider`.

## Error Handling

- Source fetch exceptions are converted into source statuses and do not crash workspace rendering.
- Failed refreshes do not promote legacy cached rows.
- Rows with malformed metadata are decoded defensively and treated as untrusted unless explicit trust fields pass.
- Missing Alpha Vantage key records `disabled`.
- GDELT rate limits record `rate_limited`.
- Macro provider failures record per-source status and do not block official catalyst display.
- Backtest returns a 400 response when no trusted events are available for the selected date range, with a message that distinguishes "no trusted events" from "no OHLC data".

## Testing Strategy

Tests must prove the trust boundary before implementation is considered complete:

- Legacy rows without trust fields are excluded from Kline trusted reads.
- Rows for one ticker never appear in another ticker workspace.
- Clinical trials with only RNA/mRNA title matches are quarantined for `MRNA`.
- Sponsor/collaborator alias matches can become trusted.
- Fresh source failures record status without promoting old untrusted rows.
- Alpha Vantage disabled state does not loop every workspace load when the key is absent.
- GDELT rate limit status does not create trusted macro rows.
- Structured macro-regime events are generated from deterministic OHLC fixtures.
- Backtest reads trusted events only and reports when no trusted events are present.
- Backtest provider loads the latest indexed run for a ticker.
- Workspace payload separates source statuses from trusted event layer counts.
- Chart/workspace tests confirm quarantined events are not passed to particle rendering.

## Acceptance Criteria

- A clean temporary database with legacy rows does not leak those rows into `/api/kline/events/<ticker>`.
- A polluted local database can be quarantined without physical deletion.
- `MRNA` no longer displays generic RNA/mRNA trials unless Moderna ownership evidence passes.
- Macro layer contains structured `macro_regime` context when benchmark OHLC fixtures are present.
- Backtest run uses only trusted, eligible events and persists an indexed latest run.
- Reopening `/kline/<ticker>` after a successful backtest shows the saved backtest layer.
- Source status chips can show `rate_limited`, `disabled`, or `empty` while trusted historical event counts remain separate.
- Tests cover all trust, quarantine, macro, and backtest persistence paths.
