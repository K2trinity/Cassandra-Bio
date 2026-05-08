# Biotech Universe Backtest Data And UI Design

Date: 2026-05-08

## Purpose

Cassandra's biotech backtest workflow must move from a four-ticker mock/demo
path to a real local research workflow over a broad U.S. biotech universe.

The immediate goals are:

- Replace the four-company research universe with `biotech_us_v1`.
- Remove the fake `Run Demo Universe` backtest path from the production K-line
  workspace.
- Fix the Backtest panel so it is readable in the dark workspace.
- Let users hide candles and view only backtest return/equity curves.
- Ingest daily OHLCV and fundamental data for the full biotech universe into
  local storage.
- Treat survivorship bias, adjusted-price correctness, and upstream rate limits
  as first-class design constraints.

This spec supersedes the earlier four-ticker B-development scope from
`2026-05-06-biotech-backtest-lab-design.md`. The A mock demo boundary remains
historically useful for isolated demos, but mock universe behavior must not be
available through the real Backtest Lab or production K-line universe controls.

## Non-Goals

- Do not build or tune a strategy to force a positive real research return.
- Do not keep `biotech_mock_v1` available as a production universe action.
- Do not fetch live market or fundamental data during page render or chart
  interaction.
- Do not treat current ETF holdings alone as a bias-free historical universe.
- Do not replace all existing K-line chart behavior; add display modes around
  it.
- Do not build a full real-time trading integration in this phase.

## Key Decisions

### 1. The Real Universe Is `biotech_us_v1`

`biotech_us_v1` is the union of:

- XBI holdings from the official SPDR S&P Biotech ETF holdings feed.
- IBB holdings from the official iShares Biotechnology ETF holdings feed.
- NASDAQ/NYSE listed common stocks classified under biotechnology,
  biopharmaceuticals, life sciences, or equivalent biotech industry categories.

The universe builder normalizes the union into local security metadata:

- `security_id`
- `ticker`
- `company_name`
- `exchange`
- `asset_type`
- `cik`
- `cusip`
- `isin`
- `is_active`
- `first_seen_date`
- `last_seen_date`
- `source_memberships`
- `classification`
- `provenance`

ETF symbols such as `XBI`, `IBB`, and `SPY` are benchmark instruments, not
company members of the strategy universe. They should be stored separately or
tagged with `asset_type = benchmark_etf`.

### 2. Survivorship Bias Is A Hard Constraint

The system must not claim a bias-free historical biotech universe if it only
uses today's surviving tickers.

The first implementation may create a current-research universe, but it must
store and show the limitation:

```text
universe_bias_status: current_constituents_only
survivorship_bias_warning: true
```

Backtests that use current constituents only must be labeled as exploratory.
They are useful for UI, data plumbing, and strategy iteration, but they are not
acceptable as final performance evidence.

The data model must be ready for a historical membership upgrade:

- Universe membership has `effective_start` and `effective_end`.
- Delisted, acquired, merged, renamed, or bankrupt companies are not silently
  dropped.
- Ticker aliases and corporate actions map historical symbols to stable
  `security_id` values.
- Missing delisting returns are explicit nulls with a coverage flag, not
  assumed zero.
- Backtest output reports universe coverage and delisting coverage.
- External symbol-change and delisted-company sources are first-class inputs,
  not optional cleanup. If those feeds are unavailable for a snapshot, the
  snapshot remains usable only as exploratory and must keep the bias warning.

### 3. Data Fetching Must Respect Rate Limits

Data ingestion runs as offline jobs, never in the page request path. Every
upstream provider gets a rate-limit policy:

- token bucket or fixed-window request budget
- provider-specific concurrency limit
- retry with exponential backoff for transient 429/5xx responses
- durable fetch log with status, timestamp, request hash, and error message
- resumable batches so a failed run does not restart from zero
- per-provider cache TTL and snapshot ID

Rate limits are not handled with unbounded sleeps inside UI routes. The K-line
workspace and backtest endpoints read local snapshots only.

### 4. Tiingo Is The Primary Daily OHLCV Source

Tiingo End-of-Day becomes the preferred formal source for daily OHLCV because
the project only needs daily bars and adjusted data quality matters more than
intraday coverage.

The ingestion layer stores both raw and adjusted fields:

- `open`
- `high`
- `low`
- `close`
- `volume`
- `adj_open`
- `adj_high`
- `adj_low`
- `adj_close`
- `adj_volume`
- `split_factor`
- `div_cash`
- `adjustment_mode`
- `source`
- `source_symbol`
- `data_snapshot_id`
- `ingested_at`

It must not fake adjusted values by setting `adj_close = close` unless the
provider explicitly indicates no adjustment is needed. If adjusted fields are
unavailable, the row is marked with `adjustment_quality = raw_only`.

yfinance can remain as an explicit development fallback, but not as the default
source for real B/C research results.

### 5. FMP And SEC Serve Different Fundamental Roles

Financial Modeling Prep is the fast normalized fundamentals source:

- income statement
- balance sheet
- cash flow statement
- key metrics and ratios where available
- quarterly and annual periods

SEC EDGAR Company Facts is the authority source:

- CIK resolution
- XBRL facts
- filing-derived validation fields
- original company-reported concept history

For biotech strategy features, the first normalized fundamentals should include:

- cash and equivalents
- short-term investments
- total debt
- operating cash flow
- free cash flow when derivable
- R&D expense
- SG&A expense
- revenue
- net income
- shares outstanding when available
- filing date
- fiscal period

Derived fields such as cash runway, burn rate, R&D intensity, and financing
risk must include source coverage flags.

## UI Design

### Backtest Panel

The Backtest panel should match the dark K-line workspace. No default white
canvas, iframe, table body, select menu, or chart background should dominate the
panel.

Controls:

- Ticker backtest action: `Run Backtest`
- Universe action: `Run Universe`
- No `Run Demo Universe` action
- Universe selector defaults to `biotech_us_v1`
- Data snapshot selector
- Strategy selector
- Risk parameter controls
- Chart display mode selector

The panel shows compact run status:

- selected universe
- selected data snapshot
- eligible ticker count
- skipped ticker count
- price coverage
- fundamental coverage
- rate-limit or stale-data warnings
- bias warning when the universe is current-constituents-only

### Chart Display Modes

The chart must support three explicit display modes:

```text
candles_with_backtest
backtest_only
candles_only
```

`candles_with_backtest` keeps the current visual behavior: candles, events, and
backtest overlays may be visible together.

`backtest_only` hides candles, candle axes, candle hit targets, and event
markers by default. It renders:

- strategy equity or return curve
- benchmark curve, usually XBI or IBB
- drawdown panel or drawdown line when available
- metric summary

`candles_only` hides backtest equity overlays and leaves the normal K-line chart
available for price and event inspection.

The selected chart mode is part of the workspace state and should survive
rerenders within the page.

## Backend API Design

### Routes To Remove Or Deprecate

Remove the production UI entry point for:

```text
POST /api/backtest/portfolio/demo/run
```

If the route is kept temporarily for test compatibility, it must be hidden from
the K-line workspace and marked deprecated. The implementation plan should
prefer removal after updating tests.

### Routes To Keep

Single ticker:

```text
POST /api/backtest/run
```

Universe:

```text
POST /api/backtest/portfolio/run
```

The universe route accepts:

- `universe_id`
- `data_snapshot_id`
- `strategy_id`
- `benchmark_id`
- `start_date`
- `end_date`
- risk parameters

It does not accept `biotech_mock_v1` or `mock_multifactor_demo` for real
research runs.

## Local Data Architecture

The accepted local stack remains:

```text
Parquet
  prices_daily
  fundamentals_normalized
  raw_provider_payloads
  factor_values
  labels_daily

DuckDB
  security_master
  ticker_aliases
  universe_membership
  data_snapshots
  provider_fetch_log
  backtest_runs
  backtest_positions
  backtest_trades
  backtest_metrics

SQLite
  trusted event store
  event provenance
  event source fetch log
```

DuckDB owns local analytical metadata. Parquet owns larger columnar datasets.
SQLite remains the event trust database because current K-line event logic
already depends on it.

## Ingestion Flow

Universe refresh:

```text
fetch XBI holdings
fetch IBB holdings
fetch NASDAQ/NYSE biotech listings
normalize securities
resolve aliases and CIKs
write security_master
write universe_membership
create universe_snapshot_id
```

Price refresh:

```text
load universe snapshot
select missing or stale tickers
fetch Tiingo EOD history or delta
validate OHLCV schema and adjusted fields
write Parquet partitions
update DuckDB data_snapshots
record provider_fetch_log
```

Fundamental refresh:

```text
load universe snapshot
resolve ticker to CIK
fetch FMP normalized statements
fetch or bulk-load SEC company facts
fetch symbol-change and delisted-company references when available
write raw payloads
normalize statements and facts
compute biotech-specific derived features
record coverage flags
```

## Backtest Metrics

The first real universe backtest report should include:

Performance and risk:

- total return
- CAGR or annualized return
- annualized volatility
- Sharpe ratio
- Sortino ratio when downside returns are available
- max drawdown
- Calmar ratio
- benchmark return
- excess return versus benchmark

Trade and exposure quality:

- trades
- active signal days
- win rate
- profit factor
- average holding period
- turnover
- average gross exposure
- average number of positions

Data credibility:

- eligible universe count
- skipped ticker count
- missing price coverage
- missing fundamental coverage
- delisting coverage
- current-constituents-only warning
- provider rate-limit or stale-data warnings

## Error Handling

- Missing Tiingo token blocks Tiingo ingestion with a clear local error; it does
  not silently fall back to yfinance for formal snapshots.
- Provider 429 responses are recorded as `rate_limited` and retried within the
  configured budget.
- Provider 5xx responses are retried with backoff and then recorded as
  `provider_error`.
- A ticker with no price history is skipped with a reason, not treated as zero
  return.
- A ticker with partial price history receives coverage metadata, and the
  backtest decides eligibility from explicit coverage rules.
- A ticker with missing fundamentals can still be price-backtested if the
  selected strategy does not require fundamentals.
- Strategies requiring fundamentals must report skipped tickers and missing
  fields.
- Backtest routes return structured errors for missing snapshot, empty universe,
  no eligible tickers, and unsupported strategy/universe combinations.

## Testing Strategy

UI tests:

- Backtest panel does not render the `Run Demo Universe` action.
- Backtest panel styles do not include large white chart/control surfaces in the
  dark workspace.
- Chart mode control exists and sends `backtest_only` to the chart renderer.
- `backtest_only` renders equity/benchmark data without candlestick elements.
- `candles_only` renders candles without backtest equity overlays.

Backend tests:

- Portfolio route rejects `biotech_mock_v1`.
- Portfolio route reads tickers from `universe_membership`, not a hard-coded
  four-ticker tuple.
- Demo portfolio route is removed or returns a deprecated/hidden status if kept
  temporarily.
- Backtest payload includes data credibility fields.
- Backtest validation checks `trades` and `active_signal_days`, not only
  `error = None`.

Data tests:

- Universe builder merges XBI, IBB, and exchange listings without duplicate
  securities.
- Benchmark ETFs are excluded from company strategy membership.
- Current-constituents-only universe snapshots carry survivorship-bias metadata.
- Price ingestion refuses to mark raw-only data as adjusted.
- Fetch log records provider, request hash, status, rate-limit state, and retry
  count.
- Failed/resumed ingestion does not duplicate rows.
- SEC/FMP fundamentals keep raw payload provenance and normalized coverage
  flags.

## Acceptance Criteria

- The K-line Backtest panel no longer shows `Run Demo Universe`.
- The mock portfolio route is removed from production UI use.
- The Backtest panel is readable in the dark workspace without a large white
  area.
- Users can switch to `backtest_only` and view the return/equity curve without
  candles.
- `biotech_us_v1` is defined as XBI + IBB + NASDAQ/NYSE biotech listings.
- Local schemas support daily OHLCV, raw/adjusted price fields, fundamentals,
  universe membership, fetch logs, and data snapshots.
- The ingestion design includes explicit rate-limit and resumability behavior.
- Backtest output includes performance, trade quality, and data credibility
  metrics.
- Exploratory backtests using current constituents are labeled with
  survivorship-bias warnings.
- B/C research paths do not use A mock positive-demo fixtures or strategy IDs.

## External References

- SPDR XBI official fund page and holdings source:
  https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-biotech-etf-xbi
- iShares IBB official fund page and holdings source:
  https://www.ishares.com/us/products/239699/ishares-biotechnology-etf
- Tiingo End-of-Day documentation:
  https://www.tiingo.com/documentation/end-of-day
- Tiingo EOD ingestion guidance:
  https://www.tiingo.com/kb/article/the-fastest-method-to-ingest-tiingo-end-of-day-stock-api-data/
- Financial Modeling Prep developer documentation:
  https://site.financialmodelingprep.com/developer/docs
- SEC EDGAR API documentation:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
