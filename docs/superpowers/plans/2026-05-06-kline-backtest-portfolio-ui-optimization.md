# K-line Backtest Portfolio UI Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing A-path K-line backtest from a single-ticker-looking demo into a four-ticker biotech universe run with a readable equity overlay and concise portfolio diagnostics.

**Architecture:** Keep the existing single-ticker `run_kline_backtest()` contract intact. Add portfolio runners that keep the real `biotech_four_v1` universe separate from the guarded `biotech_mock_v1` demo universe: ordinary `Run Universe` uses real cached OHLC tickers `MRNA/JNJ/LLY/XBI` with `multifactor_score`, while `Run Demo Universe` is the only UI entry into mock `MRNA/JNJ/LLY/ABBA`. Both paths return chart-ready normalized equity curves, concise portfolio diagnostics, and focus-ticker overlays without exposing mock/synthetic metadata. Improve the chart equity axis so a 1.00-based equity curve displays as percent return instead of repeated `$1` labels.

**Tech Stack:** Python 3.11, pandas, pytest, Flask, vanilla JS K-line workspace, React/TypeScript/D3 chart bundle, Vite.

---

## 2026-05-06 Audit Update

- Portfolio implementation is present in the worktree: `src/backtest/portfolio_runner.py`, `/api/backtest/portfolio/run`, the K-line `Run Universe` UI action, portfolio diagnostics, and focus-ticker overlays are wired.
- Canonical optimized-preview HTTP entrypoint is `python scripts/kline_preview_server.py`, which serves this worktree at `http://127.0.0.1:7917/kline/MRNA` by default. Do not use `127.0.0.1:7897` for this worktree preview because that loopback port is occupied by a local proxy; do not use the main `Cassandra` checkout service to validate worktree-only changes.
- Formal development-address profile is `python scripts/kline_preview_server.py --formal --public-host 10.21.158.104`, which binds the optimized worktree on `0.0.0.0:7897` and prints `http://10.21.158.104:7897/kline/MRNA`. This replaces the old main-checkout `app.py` process when validating the optimized K-line UI on the formal address.
- Equity-axis readability is present in source and generated bundle: equity now renders as percent return from the first equity point instead of repeated `$1` labels.
- The original mock OHLC fixture used fixed dollar moves, making high-priced tickers such as `LLY` visually flat. The fixture now uses proportional mock moves, spreads the eight demo signal days across the full visible window, and executes A-path signals with a configurable holding period instead of one-day-only exposure. The four-ticker smoke output is approximately `+31.55%` per ticker and for the portfolio over the audited window, with 37 equity changes extending through `2025-03-31`.
- Main project spec audit found one additional A-path gap: `2026-05-06-biotech-backtest-lab-design.md` calls for a holding-period or rebalance-style strategy. This pass adds `holding_period_days` to `apply_strategy()`, the K-line API request parser, the Backtest form, single-run payload `risk_parameters`, and portfolio runner propagation. Invalid values outside `1..60` are rejected at the route layer.
- Historical K-line timeframe audit found no previous day/week/month implementation. The closest historical record is `docs/superpowers/specs/2026-04-29-kline-phase2-2-daily-zoom-event-density-strategy-design.md`, which explicitly kept daily candles as the only data grain. This pass adds Day / Week / Month visual aggregation controls in `src/kline/chart/CandlestickChart.tsx` and syncs `static/vendor/pokie-chart.umd.js`.
- Strategy-shape audit found the orange curve was stair-stepped because mock A-path used only eight signal anchors over long windows and `apply_strategy()` modeled each exposure day as an independent intraday trade. This pass changes strategy execution to a T+1 entry, continuous mark-to-market holding-period state machine, combines consecutive position spans into one trade overlay, adds `exposure_summary`, scales mock signal density by window length, and exposes a non-disclosure `price_basis=demo_ohlc` diagnostic so the UI does not confuse demo OHLC results with the visible real-price candles.
- Formal-address smoke after the strategy-shape fix for `MRNA / 2016-05-07..2026-05-05 / hold=10` returned `equity_points=2607`, `equity_changed_days=521`, `active_signal_days=53`, `exposure_days=521`, `trades=53`, and `strategy_return=1.269169`. The previous same-window behavior had only `71` changed equity days from `8` active signal days.
- Realism audit found ordinary `Run Backtest` still defaulted to `mock_multifactor_demo`, which made the visible K-line workflow look like a real strategy while using hindsight-shaped demo OHLC. This pass changes `default_strategy_for_kline()` to `multifactor_score`, adds `generate_real_multifactor_signals()` from shifted trend/momentum/volatility/event features on visible OHLC, keeps mock positive shaping only behind explicit `strategy_id=mock_multifactor_demo&data_mode=mock`, and renames the UI portfolio action to `Run Demo Universe`.
- Universe realism follow-up found `POST /api/backtest/portfolio/run` still called the mock demo portfolio runner, so `Run Universe` could still produce the staircase positive-demo curve even after the single-ticker default changed. This pass adds `run_real_biotech_portfolio_backtest()` for `biotech_four_v1` using `strategy_id=multifactor_score`, `data_mode=real`, and cached real OHLC tickers `MRNA/JNJ/LLY/XBI`; moves mock `MRNA/JNJ/LLY/ABBA` behavior to explicit `POST /api/backtest/portfolio/demo/run`; and renders separate `Run Universe` / `Run Demo Universe` buttons.
- Formal-address universe smoke after the universe split for `MRNA / 2018-12-07..2026-05-05 / hold=5` returned `universe_id=biotech_four_v1`, `strategy=multifactor_score`, `tickers=MRNA,JNJ,LLY,XBI`, `portfolio_points=1861`, `portfolio_changed_days=1844`, `portfolio_return=0.05483`, `total_trades=1123`, `avg_exposure_days=1361.25`, `focus_trades=371`, and `has_mock=False`. Explicit demo route smoke returned `tickers=MRNA,JNJ,LLY,ABBA`, `portfolio_points=63`, and no public `strategy`, `universe_id`, `mock`, or `data_mode` text.
- Dead-code and visibility cleanup found that the explicit future capability placeholders (`forecast`, `range_analysis`) are tested extension points and should stay, while K-line/backtest had removable lint-level dead code in unused imports/variables. This pass removes those unused backtest imports/assignments and preserves the future capability interface.
- Saved-run visibility follow-up found the page-load backtest summary still used the old public whitelist and hid the new diagnostics. This pass exposes saved-run `exposure_summary`, `risk_parameters`, and sanitized strategy diagnostics (`price_basis`, `holding_period_days`) while continuing to suppress internal strategy ids, `data_mode`, and mock metadata.
- Formal-address smoke after the realism fix for `MRNA / 2018-12-07..2026-05-05 / hold=5` returned `strategy=multifactor_score`, `data_mode=real`, `price_basis=visible_ohlc`, `equity_points=1861`, `equity_changed_days=1711`, `active_signal_days=1556`, `exposure_days=1712`, `trades=371`, `strategy_return=0.300691`, `buy_hold_return=1.123182`, `max_drawdown=-0.1455`, and `sharpe=0.473`.
- Verification run:
  `pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp\codex-final`
  result: `99 passed`.
- Universe split verification run:
  `pytest tests/test_backtest_strategy_registry.py tests/test_backtest_mock_dataset.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py tests/test_kline_workspace_js.py tests/test_kline_preview_server.py tests/test_kline_static_bundle.py tests/test_kline_backtest_trusted_inputs.py -q --basetemp .pytest_tmp\codex-universe-real-final-3`
  result: `115 passed`.
- Dead-code and saved-diagnostics verification:
  `python -m ruff check src\backtest src\kline`
  result: `All checks passed`.
- Current K-line/backtest audit verification:
  `pytest tests/test_backtest_strategy_registry.py tests/test_backtest_mock_dataset.py tests/test_kline_backtest_runner.py tests/test_kline_web_integration.py tests/test_kline_workspace_js.py tests/test_kline_workspace_service.py tests/test_kline_preview_server.py tests/test_kline_static_bundle.py tests/test_kline_backtest_trusted_inputs.py -q --basetemp .pytest_tmp\codex-audit-final`
  result: `134 passed`.
- Wider current-worktree regression run:
  `pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_backtest_runner.py tests/test_kline_backtest_trusted_inputs.py tests/test_kline_static_bundle.py tests/test_market_data_service.py tests/test_event_ingestion_service.py tests/test_event_ingestion_trust_boundary.py tests/test_kline_event_filter.py tests/test_kline_event_trust_db.py -q --basetemp .pytest_tmp\codex-final-wide-existing`
  result: `195 passed`.
- Frontend build run from `src/kline`:
  `npm run build`
  result: TypeScript and Vite build completed successfully.

---

## Task 1: Portfolio Runner And API

**Files:**
- Create: `src/backtest/portfolio_runner.py`
- Modify: `src/kline/routes.py`
- Test: `tests/test_kline_backtest_runner.py`
- Test: `tests/test_kline_web_integration.py`

- [x] Write failing tests proving the four-ticker universe run returns `portfolio_equity_curve`, `portfolio_metrics`, `constituents`, and a `focus_ticker` payload for the requested K-line ticker.
- [x] Write failing route tests for `POST /api/backtest/portfolio/run`, including ticker/date validation and no UI-facing mock disclosure fields.
- [x] Implement `run_mock_biotech_portfolio_backtest()` in `src/backtest/portfolio_runner.py`.
- [x] Add `/api/backtest/portfolio/run` route using the same risk/date validation rules as the single-ticker endpoint.
- [x] Run focused Python tests with `--basetemp .pytest_tmp\codex-portfolio`.

## Task 2: Workspace Portfolio UI And Diagnostics

**Files:**
- Modify: `static/kline/workspace.js`
- Modify: `static/kline/workspace.css`
- Test: `tests/test_kline_workspace_js.py`

- [x] Write failing JS harness tests that the Backtest panel has a single-ticker run button and a universe run button.
- [x] Write failing JS harness tests that a universe response renders portfolio return, best/worst ticker, total trades, and constituent rows, while chart overlays use `portfolio_equity_curve` plus the focus ticker signals/trades.
- [x] Implement the panel update without showing `mock`, `synthetic`, `data_mode`, or `positive_demo_expected`.
- [x] Style the summary cards and leaderboard with the existing dark K-line design tokens.
- [x] Run focused JS tests with `--basetemp .pytest_tmp\codex-workspace`.

## Task 3: Equity Axis Readability

**Files:**
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Modify generated bundle: `static/vendor/pokie-chart.umd.js`
- Test: `tests/test_kline_static_bundle.py`

- [x] Write a failing static/bundle test that the chart formats equity ticks as return percentages.
- [x] Change the right Y-axis to format 1.00-based equity as signed percentage return from the first equity point.
- [x] Tighten equity-domain padding so small positive demo curves do not render as a near-horizontal line.
- [x] Run `npm run build` in `src/kline` and verify the generated UMD bundle updates.
- [x] Run the static bundle test.

## Task 4: Holding Period Execution And Risk Contract

**Files:**
- Modify: `src/backtest/strategy.py`
- Modify: `src/backtest/runner.py`
- Modify: `src/kline/routes.py`
- Modify: `src/backtest/portfolio_runner.py`
- Modify: `static/kline/workspace.js`
- Test: `tests/test_kline_backtest_runner.py`
- Test: `tests/test_kline_web_integration.py`
- Test: `tests/test_kline_workspace_js.py`

- [x] Write failing tests proving `apply_strategy()` keeps the latest signal active for a configured holding period.
- [x] Write failing route and UI tests proving `holding_period_days` is validated and propagated into single and portfolio runs.
- [x] Add `holding_period_days` to strategy execution, API parsing, Backtest form payloads, single-run `risk_parameters`, and portfolio runner propagation.
- [x] Verify A-path default holding period is `5` trading days and invalid route values outside `1..60` return `400`.

## Final Verification

- [x] Run:
  `pytest tests/test_backtest_mock_dataset.py tests/test_backtest_strategy_registry.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q --basetemp .pytest_tmp\codex-final`
- [x] Run:
  `npm run build`
  from `src/kline`.
- [x] Run a manual four-ticker smoke script and confirm every constituent has multiple trades and positive strategy return.
- [x] Inspect `git status --short` and `git diff --stat`.
