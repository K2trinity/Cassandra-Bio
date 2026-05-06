# Biotech Backtest Lab Design

Date: 2026-05-06

## Purpose

Cassandra's K-line backtest needs to move from a single-event demo into a
biotech research backtest system. The immediate product path has three tracks:

- **A: K-line single-ticker mock demo** for `MRNA`, `JNJ`, `LLY`, and `ABBA`.
- **B: Biotech universe backtest lab** as the main product direction.
- **C: ML research strategy** as a secondary path under the B framework.

The system must first keep the current single-ticker backtest operational. A is
allowed to use controlled mock data for presentation. B and C must not use
presentation shaping, hindsight tuning, or hidden return guarantees.

## Key Decisions

### 1. A Is Mock, Multi-Factor, And Presentation-Oriented

A remains a K-line drilldown workflow, but it must not stay pure event-driven.
The mock A strategy uses a deterministic multi-factor score:

- event factor from trusted mock events
- short/medium momentum
- volume shock
- volatility penalty
- liquidity score
- sector or benchmark regime proxy

The A mock dataset may be constructed so the resulting equity curve is positive
and visually useful. This must be done by controlling the mock input data and
factor fixtures, not by mutating the result after the backtest runs.

The UI must not display a mock warning for A. The backend payloads and stored
run metadata must still mark the source clearly:

```json
{
  "data_mode": "mock",
  "mock_scope": "biotech_mock_v1",
  "synthetic": true,
  "ui_disclosure": false,
  "positive_demo_expected": true
}
```

This keeps the demonstration polished without contaminating real research
results.

### 2. B Is The Main Product Direction

B is the real target: a multi-ticker biotech backtest lab. It runs on a universe
and compares strategy results against sector and market benchmarks.

The first B development universe can use the same four tickers while the UI and
engine are being built:

```text
biotech_four_v1: MRNA, JNJ, LLY, ABBA
```

If B uses mock fixtures during early UI development, they must be neutral
fixtures for contract testing. They must not use A's positive-demo dataset,
`positive_demo_expected`, or any hidden return shaping.

Once the engine is stable, the same framework expands to a broader biotech
universe such as XBI or curated biotech names.

B must not guarantee positive returns. It reports the actual output of the
selected data snapshot, split, strategy, and risk configuration.

### 3. C Is A Side Path Under B

C introduces ML only as one strategy backend in the universe framework. It does
not replace the deterministic multi-factor strategy.

The first ML implementation should be conservative:

- features: event, technical, liquidity, and regime factors
- labels: forward excess return vs XBI or IBB
- validation: walk-forward only
- first models: logistic regression or simple tree model
- output: probability, expected excess return, feature importance, calibration

C must not use the A mock positive-curve shaping. Any ML result must be tied to
a frozen data snapshot and IS/OS split.

## Data Architecture

Use a local research data layer before considering a server database.

```text
Parquet
  OHLC daily bars
  feature snapshots
  labels
  prediction snapshots

DuckDB
  prices_daily
  factor_values
  labels_daily
  dataset_splits
  data_snapshots
  backtest_runs
  backtest_positions
  backtest_trades
  backtest_metrics
  model_runs
  model_predictions

SQLite events.db
  trusted event store
  provenance fields
  fetch_log
```

Parquet keeps large columnar data simple and portable. DuckDB provides fast
local SQL over Parquet and small metadata tables. SQLite remains the trusted
event/provenance store because the current K-line trust boundary already uses
it.

## Daily Refresh

Daily refresh must be independent of page loads.

```text
daily refresh job
  -> refresh OHLC cache
  -> refresh trusted events
  -> update fetch_log and freshness status
  -> compute factor_values
  -> compute labels_daily
  -> create data_snapshot_id
```

K-line and backtest routes read local snapshots only. They must not fetch market
or event data synchronously during user interaction.

Each run stores:

- `data_snapshot_id`
- `universe_id`
- `split_id`
- `strategy_id`
- risk parameters
- data freshness summary
- mock metadata when applicable

## IS / OS Splits

Do not physically split databases into IS and OS. Store split definitions and
enforce them at run time.

```text
dataset_splits
  split_id
  universe_id
  train_start
  train_end
  validation_start
  validation_end
  test_start
  test_end
  data_snapshot_id
```

The default mock split is:

```text
split_id: biotech_mock_v1_2025_2026
IS: 2025-01-01 to 2025-12-31
OS: 2026-01-01 to latest cached date
```

A can run on the mock split for presentation. B and C must show IS and OS
results separately and must never tune on OS.

## Strategy Architecture

Introduce a strategy registry so the backtest runner does not hard-code one
event strategy.

```text
StrategyRegistry
  event_baseline
  mock_multifactor_demo
  multifactor_score
  ml_probability
```

### `event_baseline`

Current deterministic event score strategy. It remains useful as a control.

### `mock_multifactor_demo`

Used only by A and only for `biotech_mock_v1`. It combines event, momentum,
volume, volatility, liquidity, and regime factors. It should create more than
one or two trades and produce a positive equity curve from controlled mock
inputs.

Guardrails:

- allowed only when `data_mode = mock`
- allowed only for `mock_scope = biotech_mock_v1`
- hidden from B/C production strategy choices
- no result post-processing to force returns
- stored run metadata must mark it as mock

### `multifactor_score`

Main B strategy. It uses the same family of factors as A but runs on normal
snapshot data and reports true results.

### `ml_probability`

C strategy. It consumes frozen feature matrices and produces model scores. The
portfolio layer still controls positions and risk.

## Execution Model

The first version should stay daily-bar based:

- signal generated on aligned trading date
- execution at next trading day's open
- configurable holding period
- slippage
- max position per ticker
- max gross exposure
- optional stop loss
- benchmark comparison

A should use a holding-period or rebalance-style strategy rather than one-day
event exposure only, because a one-day event strategy produces sparse,
uninteresting equity curves.

## UI Design

### K-line Backtest Tab For A

Keep the K-line backtest tab as a single-ticker drilldown:

- ticker fixed to current K-line ticker
- strategy default: mock multi-factor demo when ticker is in mock universe
- date range
- risk controls
- equity overlay
- signal/trade overlays
- metrics
- event and factor attribution

The UI does not show that the four-company A path is mock.

### Backtest Lab For B/C

Add a separate Backtest Lab page for multi-ticker research.

```text
Top toolbar
  Universe | Split | Strategy | Run

Left panel
  tickers
  factor groups
  risk controls

Main panel
  portfolio equity vs benchmark
  IS/OS metric cards
  drawdown

Bottom panel
  ticker leaderboard
  trades
  signals
  factor attribution
  run history
```

Interaction flow:

```text
run universe backtest
  -> inspect portfolio result
  -> click ticker in leaderboard
  -> open K-line drilldown with that ticker's signals and trades
```

## Testing Strategy

Required tests:

- single-ticker A produces active signals and trades for all four tickers
- A mock run metadata includes `data_mode = mock`
- A equity curve is positive for the controlled mock dataset
- non-trading-day events align to the next trading day
- B runner rejects hidden mock positive-curve shaping
- B reports actual negative or positive returns without modification
- split enforcement prevents OS data from affecting IS tuning
- daily snapshot reads do not trigger online refresh during backtest
- ML walk-forward split does not use random train/test splitting

## Acceptance Criteria

- `MRNA`, `JNJ`, `LLY`, and `ABBA` can run A from the K-line tab.
- A is multi-factor and produces multiple trades, not only event-day trades.
- A mock equity curves are positive through controlled inputs.
- A mock nature is stored in backend metadata but not displayed in the UI.
- B has a universe-level runner and UI concept that handles multiple tickers.
- B/C cannot use A's positive-curve guarantee or mock-only shaping.
- Every backtest run records snapshot, split, universe, strategy, and risk
  parameters.
- Routes and runners read local data snapshots and do not perform synchronous
  external refreshes.

## Implementation Order

1. Stabilize current single-ticker runner.
2. Add mock metadata contract and `biotech_mock_v1` universe definition.
3. Build deterministic mock multi-factor fixtures for `MRNA`, `JNJ`, `LLY`,
   and `ABBA`.
4. Add `mock_multifactor_demo` strategy for A.
5. Update K-line backtest tab to use A's strategy and show factor attribution.
6. Add DuckDB/Parquet snapshot layer and split definitions.
7. Add universe backtest runner for B.
8. Add Backtest Lab page.
9. Add ML feature matrix and `ml_probability` strategy for C.
