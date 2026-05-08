# Biotech Data Download Executor Design

Date: 2026-05-08

## Purpose

Cassandra needs an offline data download executor that fills the local research
database for the full `biotech_us_v1` universe. The executor should download
daily adjusted OHLCV and fundamental data from free or free-tier sources, resume
after interruptions, respect provider limits, and make data credibility visible
to the backtest UI.

This spec is a follow-up to
`docs/superpowers/specs/2026-05-08-biotech-universe-backtest-data-ui-design.md`.
That earlier work created the local data model, source policies, Tiingo price
normalization, FMP/SEC fundamental normalization, provider fetch logs, and
portfolio UI contracts. This spec turns those primitives into a runnable
download workflow.

## Non-Goals

- Do not store API keys, tokens, or emails in git-tracked files.
- Do not make K-line page render or backtest routes fetch live provider data.
- Do not use yfinance as the default for formal `biotech_us_v1` snapshots.
- Do not claim research-grade survivorship-bias-free results from current
  listed companies only.
- Do not build intraday data ingestion.
- Do not build brokerage or live trading integration.
- Do not spend paid provider credits or use paid-only endpoints.

## Required Free Inputs

The executor reads secrets and provider identity from environment variables:

```text
TIINGO_API_KEY
FMP_API_KEY
SEC_USER_AGENT
```

`SEC_USER_AGENT` must identify the application and include a real contact email,
for example `CassandraBio research@example.com`. It is not a secret, but it
should still be configured outside the repository because it contains a personal
email.

Nasdaq Trader does not require an API key. The executor downloads public symbol
directory files directly.

The implementation must redact configured secrets in logs, exceptions, snapshots,
and test output. It should log only provider names, endpoint names, request
hashes, response status, retry count, and sanitized error messages.

## Provider Roles

### Tiingo

Tiingo is the primary source for daily adjusted OHLCV.

The executor uses the free account API token from `TIINGO_API_KEY` and stores
Tiingo End-of-Day rows through the existing Tiingo normalizer. Tiingo output is
partitioned under the local `prices_daily` snapshot tree and must include raw
and adjusted fields:

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
- `adjustment_quality`
- `source`
- `source_symbol`
- `security_id`
- `data_snapshot_id`
- `ingested_at`

If Tiingo returns no data for a ticker, the run records a fetch-log row and a
coverage gap. It does not silently fall back to yfinance.

### SEC EDGAR

SEC EDGAR is the authority source for fundamental facts and filing provenance.

The executor should prefer SEC bulk archives when available because they reduce
request count and are easier to resume:

- company facts bulk data
- submissions bulk data

Point lookups may be used for missing or changed tickers, but the default path
should not send one request per concept per ticker. Every request must include
`SEC_USER_AGENT` and stay below SEC fair-access limits. The local policy should
default to no more than 8 requests per second to stay below the published
10 requests per second ceiling.

SEC normalization should reuse the existing normalized fundamentals schema and
preserve:

- CIK
- fiscal period
- form type
- filing date
- accepted timestamp when available
- source concept names
- missing numeric fields
- source payload hash

### Financial Modeling Prep

FMP is an optional enrichment source, not the only source of truth.

The free FMP key is useful for:

- company profile and industry classification
- sector and exchange metadata
- fast normalized statements for symbols where free-tier endpoints allow it
- cross-checking SEC-derived fields

The executor must treat FMP free-tier quota as scarce. The default policy is a
daily budget of 240 calls, leaving room under a 250 calls/day free-tier budget.
If the budget is exhausted, the run stops FMP work cleanly and leaves resumable
checkpoints instead of retrying indefinitely.

### Nasdaq Trader

Nasdaq Trader provides public listed-symbol files and requires no key.

The executor uses Nasdaq Trader as an active listed-symbol source. It can filter
out ETFs, test issues, non-common shares, warrants, units, rights, and preferred
shares before passing symbols to the biotech classifier. Nasdaq Trader does not
provide a historical point-in-time biotech universe, so snapshots built from it
must keep the `current_constituents_only` warning.

## Universe Discovery

The first full universe build is exploratory and current-constituents-only. It
combines multiple free sources:

1. Nasdaq Trader symbol directory for active U.S. listings.
2. FMP profile or screener metadata for sector and industry hints.
3. SEC CIK mapping and submissions metadata for CIK resolution.
4. Existing ETF/known-source memberships where already supported by the
   `biotech_us_v1` builder.

The classifier includes companies if the combined metadata indicates biotech,
biopharmaceuticals, life sciences, drug discovery, therapeutics, diagnostics, or
closely related healthcare biotechnology categories.

The classifier excludes:

- ETFs and funds
- broad healthcare services companies
- hospitals and insurers
- pure medical device companies unless marked as biotech/life-science tools by
  source metadata
- warrants, units, rights, preferred shares, and test tickers

Each membership stores source evidence, including which provider supplied the
classification.

Every generated universe snapshot must include:

```text
universe_id: biotech_us_v1
universe_bias_status: current_constituents_only
survivorship_bias_warning: true
```

## Snapshot Model

The executor creates one `data_snapshot_id` for a complete run. A snapshot is
complete only when these phases finish or explicitly record skipped coverage:

1. Universe discovery.
2. Tiingo OHLCV download.
3. SEC bulk or point-facts ingestion.
4. Optional FMP enrichment.
5. Coverage summary and manifest write.

The snapshot manifest records:

- `data_snapshot_id`
- snapshot date
- provider versions or endpoint names
- universe member count
- OHLCV coverage by ticker
- fundamentals coverage by ticker and source
- fetch counts and rate-limit counts by provider
- skipped tickers with reason codes
- source hashes for universe, price, and fundamental inputs
- survivorship-bias warning status

The manifest must be deterministic except for explicit run timestamps.

## Checkpoint And Resume

The executor writes durable checkpoints after every provider unit of work.

Minimum checkpoint identity:

```text
run_id
data_snapshot_id
provider
phase
ticker
endpoint
period_start
period_end
status
attempt_count
last_error
updated_at
```

The resume logic must skip already completed units, retry retryable failures, and
preserve fatal failures for final coverage reporting.

Status values:

- `pending`
- `running`
- `success`
- `not_found`
- `rate_limited`
- `retryable_error`
- `fatal_error`
- `skipped_budget_exhausted`

The executor should be safe to interrupt with Ctrl+C. A cancelled run should
leave all completed units visible and all unfinished units resumable.

## Rate Limits

Rate limits are provider-scoped and enforced before HTTP requests.

Default policies:

```text
sec: max 8 requests/second, concurrency 1 for point requests
fmp: max 240 requests/day, concurrency 1
tiingo: configurable conservative fixed window, concurrency 1 by default
nasdaq_trader: max 1 request/second, concurrency 1
```

HTTP 429 handling:

- Record `rate_limited` in `provider_fetch_log`.
- Respect `Retry-After` if present.
- Otherwise apply exponential backoff with jitter.
- Persist the retry count in checkpoint state.
- Stop a provider phase cleanly if retry budget is exhausted.

HTTP 5xx handling:

- Retry with exponential backoff.
- Record final failure as `retryable_error` if retry budget is exhausted.

HTTP 4xx handling:

- Treat provider authentication failures as `fatal_error`.
- Treat missing ticker data as `not_found`.
- Do not continue with an invalid or missing API key.

## CLI Contract

The first executable entrypoint should be a script, not a web action:

```powershell
python scripts/download_biotech_data.py `
  --snapshot-date 2026-05-08 `
  --universe-id biotech_us_v1 `
  --start-date 2010-01-01 `
  --end-date 2026-05-08 `
  --providers nasdaq,sec,tiingo,fmp `
  --resume
```

Development and quota-safe modes:

```powershell
python scripts/download_biotech_data.py --dry-run --limit-tickers 5
python scripts/download_biotech_data.py --providers nasdaq,sec --dry-run
python scripts/download_biotech_data.py --providers tiingo --limit-tickers 5 --resume
python scripts/download_biotech_data.py --providers fmp --daily-budget 25 --resume
```

The CLI prints a compact summary:

- data snapshot id
- selected providers
- universe size
- completed units
- skipped units
- failed units
- rate-limit count
- output roots

It must not print API keys or full request URLs that include API keys.

## Local Storage

The executor writes to the existing research storage:

- DuckDB catalog tables from `src/backtest/research_db.py`
- `prices_daily` Parquet partitions for OHLCV
- `fundamentals_normalized` records for FMP and SEC facts
- `provider_fetch_log`
- checkpoint tables or checkpoint JSONL files under the research directory
- snapshot manifest JSON under the research directory

Parquet partition tokens must be validated before writing. Partial file writes
should use a temporary path and atomic replacement where practical.

## Web Integration Boundary

The web app does not launch long-running provider downloads in this phase.

The Backtest panel uses only completed local snapshots. A later UI can expose
snapshot status and coverage, but live ingestion stays offline until the job
runner has authentication, retry, and cancellation behavior tested.

## Error Handling

Missing `TIINGO_API_KEY`:

- Blocks Tiingo phases.
- Does not block SEC or Nasdaq phases.
- Produces a clear local configuration error.

Missing `FMP_API_KEY`:

- Skips FMP phases unless `--require-provider fmp` is set.
- Does not block Tiingo, SEC, or Nasdaq.

Missing `SEC_USER_AGENT`:

- Blocks SEC phases.
- Produces a clear local configuration error explaining the User-Agent
  requirement.

Invalid provider response:

- Stores the raw response hash when available.
- Records sanitized provider log metadata.
- Fails the unit without corrupting previous successful partitions.

## Testing Strategy

Tests must not make live HTTP calls by default.

Use fake HTTP clients and provider fixtures for:

- Tiingo adjusted OHLCV responses
- SEC bulk metadata and company facts
- FMP profile and statement responses
- Nasdaq Trader symbol directory files
- 429 with and without `Retry-After`
- 5xx retry exhaustion
- missing credentials
- resume after partial success
- fatal response preserving previous partitions

Add one optional manual smoke command for real credentials:

```powershell
python scripts/download_biotech_data.py --dry-run --limit-tickers 5
```

The smoke command should show planned requests and credential availability, but
it should not consume provider quota unless `--execute` or equivalent explicit
flag is supplied.

## Acceptance Criteria

- Secrets are loaded from environment variables only and are redacted in all
  logs and errors.
- Nasdaq Trader ingestion works without an API key.
- Missing SEC User-Agent blocks only SEC phases.
- Tiingo OHLCV writes adjusted daily price partitions for a small ticker set.
- SEC fundamentals write normalized rows for a small ticker set or bulk fixture.
- FMP enrichment honors a configurable daily budget and stops cleanly when the
  budget is exhausted.
- Interrupted runs can resume without repeating completed ticker/provider units.
- Provider 429/5xx behavior is logged and checkpointed.
- Generated snapshots keep `current_constituents_only` and
  `survivorship_bias_warning: true`.
- Backtest routes continue to read local snapshots only.

## References

- Tiingo API token documentation:
  https://www.tiingo.com/kb/article/where-to-find-your-tiingo-api-token/
- Tiingo End-of-Day ingestion guidance:
  https://www.tiingo.com/kb/article/the-fastest-method-to-ingest-tiingo-end-of-day-stock-api-data/
- Financial Modeling Prep pricing:
  https://site.financialmodelingprep.com/pricing-plans
- Financial Modeling Prep developer docs:
  https://intelligence.financialmodelingprep.com/developer/docs
- SEC EDGAR API documentation:
  https://www.sec.gov/edgar/sec-api-documentation
- SEC developer resources and fair-access guidance:
  https://www.sec.gov/about/developer-resources
- Nasdaq Trader symbol directory definitions:
  https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs
