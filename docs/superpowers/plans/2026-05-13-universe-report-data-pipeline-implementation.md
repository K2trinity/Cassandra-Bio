# Universe Report Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resilient current-universe data ingestion, event-price alignment, report depth modes, report database persistence with dedupe, and visible report-origin K-line labels.

**Architecture:** Extend existing ingestion, report, and K-line modules rather than introducing a second data plane. The new CLI reads the active DuckDB universe, executes the existing provider downloader in batches with retry/backoff, and optionally aligns trusted events to the resulting price snapshot. Report modes flow from Flask/API through `WorkflowService` into `DiseaseReportOrchestrator`; generated report packages are persisted to SQLite with a canonical dedupe key.

**Tech Stack:** Python 3.11, Flask, DuckDB, SQLite, pandas/Parquet, pytest, TypeScript/React/Vite K-line bundle.

---

## Task 1: Resilient Universe Ingestion Script

**Files:**
- Create: `src/data_ingestion/retry_policy.py`
- Modify: `src/data_ingestion/download_executor.py`
- Create: `scripts/ingest_universe_company_data.py`
- Test: `tests/test_provider_retry_policy.py`
- Test: `tests/test_biotech_download_executor.py`
- Test: `tests/test_ingest_universe_company_data_cli.py`

- [ ] Add a deterministic retry policy for provider results.

The policy must retry statuses `rate_limited`, `retryable_error`, and transient `failed`, honor provider `retry_after_seconds`, cap sleeps with `max_sleep_seconds`, and return the final provider result plus retry count. Tests must inject a fake sleeper so no test waits.

- [ ] Extend `DownloadRequest` with `include_tickers`, `max_provider_attempts`, and `max_retry_sleep_seconds`.

`include_tickers` filters selected members without changing the full universe snapshot. `_fetch_with_runtime_limit()` must wrap provider calls in the retry policy and record final provider logs with retry metadata.

- [ ] Add `scripts/ingest_universe_company_data.py`.

The script must:

```bash
python scripts/ingest_universe_company_data.py \
  --snapshot-date 2026-05-13 \
  --start-date 2018-01-01 \
  --end-date 2026-05-13 \
  --providers tiingo,sec,fmp \
  --batch-size 3 \
  --resume \
  --align-events
```

It loads source rows from the latest `biotech_us_v1` snapshot, chunks tickers deterministically, calls `run_download()` per batch with the full universe rows and `include_tickers`, resumes by default unless `--no-resume` is supplied, prints one JSON summary, and never prints secrets.

- [ ] Add event alignment in the script.

After downloads, for each selected ticker, load trusted events from `data/events.db`, load Tiingo OHLC for the produced data snapshot, call `align_events_for_snapshot()`, combine links, and write them with `write_event_price_links()`. If the link partition already exists, return a skipped alignment status unless `--replace-event-links` is supplied.

- [ ] Verify with targeted tests.

Run:

```bash
python -m pytest tests/test_provider_retry_policy.py tests/test_biotech_download_executor.py tests/test_ingest_universe_company_data_cli.py -q --basetemp=.pytest_tmp/universe-ingest
```

Expected: all tests pass without real network calls.

## Task 2: Report Modes And Database Persistence

**Files:**
- Create: `src/reports/disease/report_modes.py`
- Create: `src/reports/disease/report_store.py`
- Modify: `src/backtest/migrations.py`
- Modify: `src/reports/disease/clinicaltrials_harvester.py`
- Modify: `src/reports/disease/orchestrator.py`
- Modify: `src/reports/disease/narrative.py`
- Modify: `src/services/workflow_service.py`
- Modify: `app.py`
- Test: `tests/reports/disease/test_report_modes.py`
- Test: `tests/reports/disease/test_report_store.py`
- Test: `tests/reports/disease/test_clinicaltrials_harvester.py`
- Test: `tests/reports/disease/test_workflow_service.py`

- [ ] Add `ReportModeConfig` for `fast`, `medium`, and `pro`.

Mode limits are `100`, `250`, and `500` retained records. Company layer quotas scale as 30 percent catalyst, 50 percent expansion, and 20 percent track record. Narrative sample caps should keep the LLM prompt bounded while preserving aggregate counts.

- [ ] Scale company harvester layer page sizes and selection quotas.

For `max_records <= 100`, use the fast `30/50/20` catalyst/expansion/track-record distribution. For larger modes, scale layer page sizes and selection quotas proportionally.

- [ ] Thread `report_mode` through API and workflow.

`/api/analyze` must accept `report_mode` in JSON and form requests. `WorkflowService.run/stream()` and `DiseaseReportOrchestrator.run/stream()` must accept it. Invalid modes should return HTTP 400.

- [ ] Bound narrative payload size.

`build_narrative_payload()` should include full mode counts and representative records, not every retained record for `medium`/`pro`. Persist the selected mode in `SourceAudit.details`.

- [ ] Persist report rows into SQLite.

Add a migration creating `report_documents` with `dedupe_key UNIQUE`. `ReportStore.save()` inserts one row per unique stable report package and returns `{status, report_id, inserted}`. Re-running the same package with different artifact paths or regenerated narrative text must not insert a duplicate.

- [ ] Integrate persistence after writer output.

After `renderer_adapter.render_all()`, save package, narratives, artifact paths, query, target metadata, and mode. Add `report_store` fields to the workflow state and completion payload.

- [ ] Verify with targeted tests.

Run:

```bash
python -m pytest tests/reports/disease/test_report_modes.py tests/reports/disease/test_report_store.py tests/reports/disease/test_clinicaltrials_harvester.py tests/reports/disease/test_workflow_service.py -q --basetemp=.pytest_tmp/report-modes
```

Expected: all tests pass without real ClinicalTrials or Gemini calls.

## Task 3: Report-Origin K-Line Labels

**Files:**
- Modify: `static/kline/workspace.js`
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Modify: `tests/test_kline_workspace_js.py`
- Modify: `tests/reports/disease/test_report_kline_bridge.py`

- [ ] Add UI helpers for report-derived events.

Detect `metadata.derived_from_report === true` or `metadata.report_bridge === true`. Keep `source` and `category` unchanged.

- [ ] Label report-derived events in static K-line UI.

Catalyst cards should show `clinicaltrials · from report`. Event details should show `Origin: Report`, report company, and report artifact path when present.

- [ ] Label report-derived events in the React/canvas chart.

Tooltip should include `Origin: Report`. Marker drawing should add a subtle outer report ring without changing the clinical marker color.

- [ ] Update TypeScript metadata fields.

Add optional `derived_from_report`, `report_bridge`, `report_company_name`, `report_path`, and `report_target_type` to `BiotechEventMetadata`.

- [ ] Verify with targeted tests and build.

Run:

```bash
python -m pytest tests/test_kline_workspace_js.py tests/reports/disease/test_report_kline_bridge.py -q --basetemp=.pytest_tmp/kline-report-origin
cd src/kline && npm run build
```

Expected: tests pass and Vite builds the chart bundle.

## Task 4: Documentation, Final Verification, Merge, And Server Update

**Files:**
- Modify: `README.md`

- [ ] Update README.

Document the current universe count inspection command, the server database deployment fact, report modes, the ingestion script, event alignment output, and report-origin K-line labels.

- [ ] Run final verification.

Run:

```bash
python -m pytest tests/test_provider_retry_policy.py tests/test_biotech_download_executor.py tests/test_ingest_universe_company_data_cli.py tests/reports/disease/test_report_modes.py tests/reports/disease/test_report_store.py tests/reports/disease/test_clinicaltrials_harvester.py tests/reports/disease/test_workflow_service.py tests/test_kline_workspace_js.py tests/reports/disease/test_report_kline_bridge.py -q --basetemp=.pytest_tmp/final
cd src/kline && npm run build
```

- [ ] Merge and push.

Merge `feature/universe-report-data-pipeline` into local `main`, preserve unrelated user changes in the original checkout, and push to `origin/main` only after verifying `origin` is `K2trinity/Cassandra-Bio`.

- [ ] Update server.

SSH to `ubuntu@165.154.4.149`, inspect `/home/ubuntu/cassandra-bio`, preserve server-only `.dockerignore` and compose state, pull fast-forward, restart the app container, apply SQLite migrations, and run a conservative dry run of the ingestion script. Run a small live batch only if credentials are present and the command can resume.
