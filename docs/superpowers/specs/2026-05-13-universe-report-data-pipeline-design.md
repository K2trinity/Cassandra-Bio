# Universe Report Data Pipeline Design

## Current State

Local and server inspection on 2026-05-13 shows the production universe is `biotech_us_v1` in `data/research/cassandra_research.duckdb`. The latest active snapshot is `2026-05-10` with 12 active tickers: `ALNY`, `AMGN`, `BEAM`, `BIIB`, `BMRN`, `CRSP`, `EDIT`, `GILD`, `MRNA`, `NTLA`, `REGN`, and `VRTX`.

The server deployment at `/home/ubuntu/cassandra-bio` mounts `./data` into the `cassandra-bio-app` container. The server has both `data/research/cassandra_research.duckdb` and `data/events.db`; the container can read the DuckDB database and reports the same 12-member universe. The event database has report-provenance tables, but `event_source_documents` and `event_extraction_runs` are currently empty.

Reports are currently persisted mainly as files under `final_reports`. The existing report-to-K-line bridge persists derived company report clinical-trial milestone events into `data/events.db`, with metadata flags such as `derived_from_report` and `report_bridge`, but the K-line UI does not visibly label those events as report-derived.

## Goals

1. Add an automated, resumable universe ingestion script that works under API limits, backs off on provider limits, and can gradually ingest current-universe stock/company data.
2. Align event rows to price dates for the newly ingested price snapshot so downstream backtests can use auditable event-price links.
3. Add report depth modes: `fast`, `medium`, and `pro`.
4. Persist generated company and disease reports into the server database with duplicate detection.
5. Make report-derived K-line events visually and textually identifiable while preserving the factual source and clinical category.
6. Update README with the new operational commands and deployed database facts.

## Report Modes

The modes are intentionally capped to balance data depth against Gemini 3.1 Pro latency and prompt size:

| Mode | Retained Records | Company Layer Ratio |
| --- | ---: | --- |
| `fast` | 100 | current behavior: catalyst 30, expansion 50, track record 20 |
| `medium` | 250 | scaled: catalyst 75, expansion 125, track record 50 |
| `pro` | 500 | scaled: catalyst 150, expansion 250, track record 100 |

The report package stores the retained records for the selected mode. The LLM narrative payload does not pass every retained record verbatim for `medium` and `pro`; it passes all aggregate counts plus a representative capped sample per section. This keeps the report truthful and avoids hidden summarization failure from oversized contexts.

## Data Ingestion

The new script reads the current DuckDB universe snapshot and passes the full source rows into the existing `run_download()` executor. It runs selected tickers in deterministic batches without rewriting the universe as a partial universe. Checkpoints remain keyed by provider, ticker, endpoint, and date window so interrupted runs can resume.

Provider calls use the existing fixed-window rate limiter plus a new retry policy for provider-returned `rate_limited`, `retryable_error`, and transient `failed` responses. Retry waits honor `Retry-After` when present and otherwise use bounded exponential backoff. The cap is configurable so production runs can wait, while tests and dry runs stay fast.

After successful price ingestion, the script loads trusted events for each selected ticker, loads the matching Tiingo OHLC rows, and writes event-price links under `data/research/event_price_links/data_snapshot_id=<snapshot>`. Existing link partitions are not overwritten unless explicitly requested.

## Report Persistence

A SQLite report store is added to `data/events.db` because report-derived K-line events and event provenance already live there. The store uses a canonical dedupe key over target type, target name, company name, report mode, retained NCT IDs, source audit, and rendered report hash. Re-running the same report does not insert another row.

The persisted row includes query, target fields, mode, package JSON, narratives JSON, artifact paths, source audit, and created/updated timestamps. This supports server-side inspection and later UI history without replacing the existing file artifact workflow.

## K-Line Labeling

The bridge keeps `source="clinicaltrials"` and clinical categorization intact because that remains the factual source and event type. The UI reads `metadata.derived_from_report` or `metadata.report_bridge` and adds:

- a report-derived ring on event markers,
- an `Origin: Report` line in marker tooltips,
- `from report` labeling in catalyst cards,
- report company/path details in the event details panel.

This makes provenance clear without disrupting layer routing or backtest semantics.

## Deployment

Deployment flow remains:

1. Merge to `origin/main`.
2. SSH as `ubuntu@165.154.4.149`.
3. Inspect `/home/ubuntu/cassandra-bio` before pulling.
4. Preserve server-only `.dockerignore` and compose files.
5. Pull fast-forward, rebuild/restart the app container, apply SQLite migrations, and run the ingestion script in conservative batches.

Server secrets are never printed; only configured environment variables inside the container are used.
