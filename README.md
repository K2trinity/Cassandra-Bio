# Cassandra-Bio

Cassandra-Bio is a Flask-based biomedical research workspace for disease and company reports, current-universe market data ingestion, event-to-price alignment, K-line review, and backtest analysis.

The deployed app is served from the Cassandra-Bio repository and currently uses persisted server data under `/home/ubuntu/cassandra-bio/data`.

## Current Data State

As checked on 2026-05-13, the active research universe is:

- `universe_id`: `biotech_us_v1`
- latest snapshot date: `2026-05-13`
- current active universe count: `37`
- tickers: `AARD`, `ABEO`, `ABOS`, `ABUS`, `ABVC`, `ACAD`, `ACRS`, `ACRV`, `ACTU`, `ACXP`, `ADCT`, `ADIL`, `ADPT`, `ADXN`, `AEON`, `AGIO`, `AGMB`, `AKBA`, `AKTS`, `AKTX`, `ALDX`, `ALGS`, `ALLO`, `ALLR`, `ALMR`, `ALNY`, `AMGN`, `BEAM`, `BIIB`, `BMRN`, `CRSP`, `EDIT`, `GILD`, `MRNA`, `NTLA`, `REGN`, `VRTX`

Inspect the local universe count:

```powershell
@'
import duckdb
con = duckdb.connect("data/research/cassandra_research.duckdb", read_only=True)
latest = con.execute("""
    select max(member_from)
    from universe_membership
    where universe_id = 'biotech_us_v1'
""").fetchone()[0]
tickers = [
    row[0]
    for row in con.execute("""
        select ticker
        from universe_membership
        where universe_id = 'biotech_us_v1'
          and member_from = ?
        order by ticker
    """, [latest]).fetchall()
]
print({"snapshot_date": str(latest), "active_count": len(tickers), "tickers": tickers})
'@ | C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -
```

Inspect the event and report database:

```powershell
@'
import sqlite3
con = sqlite3.connect("data/events.db")
for table in ["biotech_events", "event_source_documents", "event_extraction_runs", "report_documents"]:
    try:
        print(table, con.execute(f"select count(*) from {table}").fetchone()[0])
    except sqlite3.Error as exc:
        print(table, exc)
'@ | C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -
```

On the server, Docker Compose mounts `./data:/app/data`, so `data/events.db` and `data/research/cassandra_research.duckdb` are deployed databases, not container-only files.

## Report Modes

The report workflow supports three depth modes through the web UI and `/api/analyze`:

- `fast`: retains up to 100 records. This is the default and matches the previous quick report size.
- `medium`: retains up to 250 records.
- `pro`: retains up to 500 records.

Company reports preserve the same layer shape at larger sizes:

- catalyst tracker: 30%
- expansion map: 50%
- track record: 20%

For Gemini 3.1 Pro summarization, the package keeps aggregate counts for the full retained set, while the narrative payload sends representative records only. This keeps `medium` and `pro` usable without pushing every retained row into the LLM prompt.

Generated disease and company reports are persisted to SQLite in `report_documents`. The store uses a stable content dedupe key, so re-running the same report package with regenerated wording or different output paths does not insert a duplicate row.

## Current-Universe Data Ingestion

Use the resumable ingestion script to fetch additional current-universe market/provider data in small batches while respecting provider rate limits:

First expand the universe snapshot itself. This writes only the DuckDB universe catalog and does not call Tiingo, SEC, or FMP:

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe scripts/ingest_universe_company_data.py `
  --snapshot-date 2026-05-13 `
  --start-date 2026-05-01 `
  --end-date 2026-05-13 `
  --expand-from-nasdaq-trader `
  --max-expansion-tickers 25 `
  --write-universe-only
```

`--expand-from-nasdaq-trader` reads Nasdaq Trader's public symbol directories with a one-request-per-second limiter, filters active common-stock names by biotech/pharma keywords, dedupes against the latest DuckDB snapshot, and prints `universe_expansion.added_tickers`. Use `--dry-run` to preview without writing. For a manually audited list, pass one or more `--universe-expansion-csv` files with columns `ticker`, `company_name`, `exchange`, and `asset_type`; optional columns include `industry`, `cik`, `source_weight`, `cusip`, `isin`, and `source`.

Then fetch company stock/provider data in small resumable batches:

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe scripts/ingest_universe_company_data.py `
  --snapshot-date 2026-05-13 `
  --start-date 2018-01-01 `
  --end-date 2026-05-13 `
  --providers tiingo,sec,fmp `
  --batch-size 3 `
  --resume `
  --align-events
```

Useful controls:

- `--limit-tickers N`: run a safe partial batch first.
- `--dry-run`: inspect planned batches without writing provider data.
- `--no-resume`: disable checkpoint reuse for a deliberately fresh run.
- `--max-provider-attempts`: cap retries per provider request.
- `--max-retry-sleep-seconds`: cap sleep time after rate-limit responses.
- `--write-universe-only`: write the expanded universe snapshot and skip provider calls.
- `--expand-from-nasdaq-trader`: add current active-listed biotech/pharma keyword matches from Nasdaq Trader.
- `--universe-expansion-csv PATH`: add audited universe rows from CSV.
- `--replace-event-links`: rewrite existing event-price link partitions for the produced snapshot.

The script reads the latest `biotech_us_v1` universe snapshot, optionally expands it before planning batches, keeps provider downloads scoped to selected tickers, retries transient provider failures, and prints one JSON summary without secrets.

## Event Alignment And K-Line Labels

When `--align-events` is enabled, the ingestion script loads trusted events from `data/events.db`, aligns them to the generated price snapshot, and writes event-price links. Existing link partitions are skipped unless `--replace-event-links` is supplied.

Company reports also bridge selected report-derived clinical events into K-line. The persisted event metadata includes:

- `derived_from_report`
- `report_bridge`
- `report_company_name`
- `report_path`
- `report_target_type`

The K-line UI keeps the original event `source` and `category`, but visually marks report-derived events:

- catalyst cards show a `Report` badge and `from report` source label.
- event details show `Origin: Report`, report company, and report path.
- the canvas chart draws an outer ring and tooltip origin label for report-derived markers.

## Quick Start

### Prerequisites

- Python 3.11
- Google Cloud project with Vertex AI enabled
- `gcloud` CLI configured for ADC
- optional provider credentials for live ingestion, such as Tiingo/FMP/SEC-compatible settings used by the existing ingestion stack

### Install

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pip install -r requirements.txt
```

Use the project Python 3.11 interpreter above. Do not run the app from `F:/miniconda/python.exe`, because that base environment does not include the backtest data dependencies such as `yfinance`.

### Configure

```powershell
copy .env.example .env
gcloud auth application-default login
```

Set at least:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`

### Run

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe app.py
```

Open:

```text
http://127.0.0.1:5000/investigation
```

## Runtime Architecture

- Flask + Socket.IO web app: `app.py`
- report workflow facade: `src/services/workflow_service.py`
- disease/company orchestrator: `src/reports/disease/orchestrator.py`
- report modes: `src/reports/disease/report_modes.py`
- report persistence: `src/reports/disease/report_store.py`
- provider ingestion executor: `src/data_ingestion/download_executor.py`
- provider retry policy: `src/data_ingestion/retry_policy.py`
- current-universe ingestion CLI: `scripts/ingest_universe_company_data.py`
- K-line static workspace: `static/kline/workspace.js`
- K-line React chart bundle: `src/kline/`

## Testing

Run the focused checks for the current universe/report/K-line work:

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest `
  tests/test_provider_retry_policy.py `
  tests/test_biotech_download_executor.py `
  tests/test_ingest_universe_company_data_cli.py `
  tests/reports/disease/test_report_modes.py `
  tests/reports/disease/test_report_store.py `
  tests/reports/disease/test_clinicaltrials_harvester.py `
  tests/reports/disease/test_workflow_service.py `
  tests/test_investigation_ui.py `
  tests/test_kline_workspace_js.py `
  tests/reports/disease/test_report_kline_bridge.py `
  -q --basetemp=.pytest_tmp/final
```

Build the K-line chart bundle:

```powershell
cd src/kline
npm run build
```

Run the full Python test suite:

```powershell
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests
```

## Server Update Path

The production-style server path is:

```text
ubuntu@165.154.4.149:/home/ubuntu/cassandra-bio
```

The public investigation URL is:

```text
http://cassandra-bio.165.154.4.149.sslip.io/investigation
```

Before pulling on the server, inspect the worktree and preserve server-only files such as `.dockerignore`, Docker Compose files, data, logs, final reports, and secret mounts. Prefer `git pull --ff-only` when the server worktree has no conflicting tracked edits.

## License

See `LICENSE`.
