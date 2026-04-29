# Biotech Research Stack V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a local-first biotech research stack that adds a PIT-aware event data contract, upgrades the K-Line page into a biotech workspace, hardens backtest execution rules, and replaces the disease-survey `Sponsor Analysis` / empty `Safety Profile` output with a technical-route summary plus market landscape timing-and-share analysis without blocking on slot/handoff unification.

**Architecture:** Keep Flask + Jinja + the existing UMD chart bundle as the page shell, but move the data plane to a normalized event/source/fact schema persisted in SQLite with Parquet market caches. Reuse the existing disease survey structured composer path for Day 4, but repurpose the report layer to (a) crawl official sponsor `Science` / `Our Approach` / `Platform` / `Our Story` pages for technical-route evidence and (b) use already-harvested ClinicalTrials.gov timing fields plus sponsor revenue disclosures to build clinical-velocity and competitive-share tables. Treat slot/handoff writer unification as deferred architecture work so Days 1-4 can validate the outputs quickly without rewriting the entire report stack.

**Tech Stack:** Flask, Flask-SocketIO, Jinja2, React 19 UMD bundle, D3, pandas, SQLite, Parquet, pytest, requests, BeautifulSoup, ClinicalTrials.gov API, SEC EDGAR API, FDA public pages/RSS, sponsor websites / investor-relations pages, PR Newswire RSS, GlobeNewswire RSS, Fierce Biotech RSS, BiomedBERT, SapBERT, Qwen2.5-7B-Instruct

---

## Scope Note

This plan spans four subsystems that normally could be separate plans:

1. Data plane and extraction contracts
2. K-Line biotech workspace UX
3. Backtest execution credibility
4. Disease survey technical-route and market-competition intelligence

They remain in one plan because the user explicitly requested a single four-day execution spec and the artifacts are sequentially dependent:

- Day 2 depends on Day 1 event contracts
- Day 3 depends on Day 1 event contracts and Day 2 UI semantics
- Day 4 depends on Day 1 extraction structure and existing disease survey rendering

To keep this safe, each day ends with a concrete release gate and does not require the next day to begin unless the previous gate is green.

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/backtest/event_models.py` | TypedDict / helper functions for standardized `biotech_events`, source records, and fact rows |
| `src/backtest/market_sessions.py` | Session classification and `release_timestamp -> aligned_trade_date` helpers |
| `src/tools/sec_edgar_client.py` | Pull and normalize biotech-relevant SEC 8-K / Form 25 / Form 15 events |
| `src/tools/fda_calendar_client.py` | Pull and normalize FDA advisory / milestone calendar entries |
| `src/tools/rss_event_client.py` | Shared RSS parsing helpers for PR Newswire, GlobeNewswire, and Fierce Biotech |
| `tests/test_events_db_schema.py` | Schema and migration tests for PIT-aware SQLite tables |
| `tests/test_market_sessions.py` | Session classification and trade-date alignment tests |
| `tests/test_sec_edgar_client.py` | SEC event normalization tests |
| `tests/test_fda_calendar_client.py` | FDA event normalization tests |
| `tests/test_rss_event_client.py` | RSS parsing and normalization tests |
| `tests/test_backtest_execution_rules.py` | Execution timing, slippage, and event filtering tests |
| `src/tools/company_approach_client.py` | Fetch and extract official sponsor `Science` / `Our Approach` / `Platform` / `Our Story` pages |
| `src/engines/report_engine/disease_survey/technical_route.py` | Build structured sponsor technical-route summaries from official website facts |
| `src/engines/report_engine/disease_survey/market_landscape_analysis.py` | Assemble clinical-timing and competitive-share summary tables for one disease market |

### Modified Files

| File | Change |
|------|--------|
| `src/backtest/events_db.py` | Replace the minimal event table with PIT-aware tables and helper APIs |
| `src/services/event_ingestion_service.py` | Orchestrate official source + RSS source ingestion using the new schema |
| `src/services/market_data_service.py` | Expose cache metadata or helpers needed by the upgraded K-Line workspace |
| `src/backtest/signals.py` | Gate signal eligibility by confidence, timestamp precision, and source tier |
| `src/backtest/runner.py` | Enforce session-aware execution rules, slippage multipliers, and execution audit outputs |
| `src/kline/chart/types.ts` | Extend chart config and event types with release/alignment/session/confidence/source metadata |
| `src/kline/chart/CandlestickChart.tsx` | Render dual-timeline particle semantics and workspace-driven highlighting |
| `src/kline/chart/index.tsx` | Pass through the extended chart config |
| `templates/kline_report.html` | Promote K-Line into a biotech workspace with Events / Source / Facts / Backtest tabs |
| `app.py` | Hydrate K-Line from the normalized event schema and expose any route helpers needed for the upgraded page |
| `src/engines/report_engine/disease_survey/models.py` | Extend trial and sponsor models with timing, website, and revenue-source fields needed by Day 4 |
| `src/engines/report_engine/disease_survey/aggregator.py` | Carry ClinicalTrials.gov timing fields into state and prepare sponsor website / benchmark lookup hints |
| `src/engines/report_engine/disease_survey/renderer.py` | Remove `Sponsor Analysis`, render `Technical Route Summary`, and upgrade `Market Landscape` / `CNS Benchmark` |
| `src/engines/report_engine/disease_survey/composer.py` | Drop the sponsor section and render the richer Day 4 summary tables/widgets in stable order |
| `src/engines/report_engine/disease_survey/__init__.py` | Re-export the new Day 4 renderer helpers and stop exporting deleted sponsor-only helpers |
| `src/tools/pubmed_client.py` | Restrict `CNS Benchmark` literature retrieval to top-50 journals within the last five years |
| `src/engines/harvest/llm/prompts.py` | Strengthen PubMed / CNS benchmark query generation beyond the raw user query |
| `src/prompts/bioharvest/query_generation.txt` | Encode disease synonyms, target terms, mechanism terms, and top-journal constraints in query prompts |
| `tests/test_event_ingestion_service.py` | Expand ingestion tests for new source classes and schema writes |
| `tests/test_kline_web_integration.py` | Update UI integration assertions for the biotech workspace |
| `tests/test_backtest_api.py` | Assert new execution audit and bias warnings appear in API responses |
| `tests/test_disease_survey_models.py` | Keep Day 4 timing / website / revenue fields optional and type-safe |
| `tests/test_disease_survey_aggregator.py` | Keep start/completion dates preserved when harvest rows already provide them |
| `tests/test_disease_survey_renderer.py` | Keep the new Day 4 technical-route, market-landscape, and CNS benchmark payloads rendered correctly |
| `tests/test_disease_survey_composer.py` | Keep `Sponsor Analysis` removed and the new Day 4 sections ordered correctly |
| `tests/test_disease_survey_e2e.py` | Keep the full disease survey including the new Day 4 structure stable end to end |

### Deferred on Purpose

| File | Reason |
|------|--------|
| `src/graph/nodes/writer_node.py` | Slot/handoff writer unification is explicitly deferred until after fast feature validation |
| `src/agents/report_writer.py` | Generic writer prompt overhaul is deferred; Day 4 uses the disease survey structured route |
| `src/backtest/market_consensus.py` | PIT market-consensus table is deferred because current free/free-tier sources are insufficiently stable |

## Release Gates

1. **Day 1 Gate:** PIT-aware event/source/fact schema exists, free-source feasibility is documented, and extraction responsibilities are split between deterministic parsers and model-assisted stages.
2. **Day 2 Gate:** `/kline/<ticker>` is defined as a biotech workspace with dual-time semantics and Source/Facts panes, not just a chart + backtest widget.
3. **Day 3 Gate:** Backtests use explicit event alignment rules and execution audits; no default path uses event dates that can leak future knowledge.
4. **Day 4 Gate:** Disease survey reports remove `Sponsor Analysis`, replace `Safety Profile` with a summary-oriented `Technical Route Summary`, upgrade `Market Landscape` with clinical-timing plus same-wave / same-class competitive share analysis, and tighten `CNS Benchmark` to a top-50-journal / last-5-years evidence scope without requiring slot/handoff writer changes.

## Day 1 Release Gate

Outcome: the project has a local-first, PIT-aware event data plane and a documented extraction contract that does not depend on `compiled_context_text`.

### Task 1: Add PIT-Aware SQLite Schema for Events, Sources, Facts, and Tickers

**Files:**
- Create: `src/backtest/event_models.py`
- Modify: `src/backtest/events_db.py`
- Create: `tests/test_events_db_schema.py`

- [ ] **Step 1: Write the failing schema test**

```python
def test_init_db_creates_pit_tables(tmp_path, monkeypatch):
    from src.backtest import events_db

    db_path = tmp_path / "events.db"
    monkeypatch.setattr(events_db, "DB_PATH", db_path)

    events_db.init_db()

    conn = events_db._get_conn()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "biotech_events" in tables
    assert "event_source_records" in tables
    assert "event_facts" in tables
    assert "instruments" in tables
    assert "ticker_history" in tables
    assert "price_sessions" in tables
```

- [ ] **Step 2: Run the schema test and confirm failure**

Run: `pytest tests/test_events_db_schema.py::test_init_db_creates_pit_tables -v`

Expected: FAIL because the new tables do not exist yet.

- [ ] **Step 3: Create the event row contracts**

```python
# src/backtest/event_models.py
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


TimestampPrecision = Literal["minute", "hour", "date_only", "unknown"]
SessionLabel = Literal["premarket", "regular_session", "after_close", "date_only", "unknown"]
SourceTier = Literal["official", "presswire", "news", "supplemental"]


class BiotechEventRow(TypedDict):
    event_id: str
    instrument_id: str
    ticker: str
    event_type: str
    release_timestamp: str
    timestamp_precision: TimestampPrecision
    session_label: SessionLabel
    aligned_trade_date: str
    priority: int
    sentiment: str
    materiality_score: float
    confidence_score: float
    source_tier: SourceTier
    source: str
    catalyst: str
    tradable_open_price: NotRequired[float | None]
```

- [ ] **Step 4: Expand `init_db()` to create the new schema**

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS biotech_events (
        event_id TEXT PRIMARY KEY,
        instrument_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        event_type TEXT NOT NULL,
        release_timestamp TEXT NOT NULL,
        timestamp_precision TEXT NOT NULL,
        session_label TEXT NOT NULL,
        aligned_trade_date TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 3,
        sentiment TEXT NOT NULL DEFAULT 'neutral',
        materiality_score REAL NOT NULL DEFAULT 0.0,
        confidence_score REAL NOT NULL DEFAULT 0.0,
        source_tier TEXT NOT NULL DEFAULT 'supplemental',
        source TEXT NOT NULL,
        catalyst TEXT NOT NULL,
        tradable_open_price REAL
    )
""")
```

Also create:
- `event_source_records`
- `event_facts`
- `instruments`
- `ticker_history`
- `price_sessions`

- [ ] **Step 5: Re-run the schema test and make it pass**

Run: `pytest tests/test_events_db_schema.py::test_init_db_creates_pit_tables -v`

Expected: PASS

- [ ] **Step 6: Commit the PIT schema**

```bash
git add src/backtest/event_models.py src/backtest/events_db.py tests/test_events_db_schema.py
git commit -m "feat(data): add PIT-aware biotech event schema"
```

### Task 2: Add Session Classification and Trade-Date Alignment Helpers

**Files:**
- Create: `src/backtest/market_sessions.py`
- Create: `tests/test_market_sessions.py`

- [ ] **Step 1: Write failing tests for session classification**

```python
def test_classify_session_labels_after_close():
    from src.backtest.market_sessions import classify_session

    assert classify_session("2026-04-22T16:35:00-04:00") == "after_close"


def test_align_trade_date_for_after_close_uses_next_trading_day():
    from src.backtest.market_sessions import align_trade_date

    assert align_trade_date(
        "2026-04-22T16:35:00-04:00",
        timezone_name="America/New_York",
    ) == "2026-04-23"
```

- [ ] **Step 2: Run the market-session tests and confirm failure**

Run: `pytest tests/test_market_sessions.py -q`

Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Implement the smallest useful session helpers**

```python
# src/backtest/market_sessions.py
from __future__ import annotations

from datetime import datetime, time, timedelta


def classify_session(release_timestamp: str) -> str:
    ts = datetime.fromisoformat(release_timestamp)
    local_t = ts.timetz().replace(tzinfo=None)
    if local_t < time(9, 30):
        return "premarket"
    if local_t >= time(16, 0):
        return "after_close"
    return "regular_session"


def align_trade_date(release_timestamp: str, timezone_name: str = "America/New_York") -> str:
    ts = datetime.fromisoformat(release_timestamp)
    session = classify_session(release_timestamp)
    if session == "after_close":
        return (ts.date() + timedelta(days=1)).isoformat()
    if session == "regular_session":
        return (ts.date() + timedelta(days=1)).isoformat()
    return ts.date().isoformat()
```

- [ ] **Step 4: Add an explicit date-only fallback helper**

```python
def align_date_only(date_text: str) -> str:
    dt = datetime.fromisoformat(f"{date_text}T00:00:00")
    return (dt.date() + timedelta(days=1)).isoformat()
```

- [ ] **Step 5: Re-run the market-session tests until green**

Run: `pytest tests/test_market_sessions.py -q`

Expected: PASS

- [ ] **Step 6: Commit the alignment helpers**

```bash
git add src/backtest/market_sessions.py tests/test_market_sessions.py
git commit -m "feat(backtest): add session-aware trade date alignment helpers"
```

### Task 3: Add Official Source Clients for SEC EDGAR and FDA Calendar

**Files:**
- Create: `src/tools/sec_edgar_client.py`
- Create: `src/tools/fda_calendar_client.py`
- Create: `tests/test_sec_edgar_client.py`
- Create: `tests/test_fda_calendar_client.py`

- [ ] **Step 1: Write failing SEC normalization tests**

```python
def test_sec_8k_normalizes_to_corporate_event():
    from src.tools.sec_edgar_client import normalize_sec_filing

    filing = {
        "ticker": "MRNA",
        "filedAt": "2026-04-22T16:35:00-04:00",
        "form": "8-K",
        "headline": "Moderna reports topline clinical data",
    }

    row = normalize_sec_filing(filing, instrument_id="inst_mrna")

    assert row["event_type"] == "corporate_update"
    assert row["session_label"] == "after_close"
    assert row["aligned_trade_date"] == "2026-04-23"
```

- [ ] **Step 2: Write failing FDA normalization tests**

```python
def test_fda_calendar_entry_normalizes_to_regulatory_event():
    from src.tools.fda_calendar_client import normalize_fda_calendar_entry

    entry = {
        "ticker": "BIIB",
        "meeting_date": "2026-05-18",
        "title": "Peripheral and Central Nervous System Drugs Advisory Committee",
    }

    row = normalize_fda_calendar_entry(entry, instrument_id="inst_biib")

    assert row["event_type"] == "advisory_committee"
    assert row["timestamp_precision"] == "date_only"
    assert row["aligned_trade_date"] == "2026-05-19"
```

- [ ] **Step 3: Run the new client tests and confirm failure**

Run: `pytest tests/test_sec_edgar_client.py tests/test_fda_calendar_client.py -q`

Expected: FAIL because neither client exists yet.

- [ ] **Step 4: Implement normalization-first clients**

```python
# src/tools/sec_edgar_client.py
from src.backtest.market_sessions import align_trade_date, classify_session


def normalize_sec_filing(filing: dict, instrument_id: str) -> dict:
    release_ts = filing["filedAt"]
    return {
        "event_id": f"sec-{filing['ticker']}-{filing['form']}-{release_ts}",
        "instrument_id": instrument_id,
        "ticker": filing["ticker"],
        "event_type": "corporate_update",
        "release_timestamp": release_ts,
        "timestamp_precision": "minute",
        "session_label": classify_session(release_ts),
        "aligned_trade_date": align_trade_date(release_ts),
        "priority": 2,
        "sentiment": "neutral",
        "materiality_score": 0.6,
        "confidence_score": 0.9,
        "source_tier": "official",
        "source": "sec_edgar",
        "catalyst": filing["headline"],
    }
```

```python
# src/tools/fda_calendar_client.py
from src.backtest.market_sessions import align_date_only


def normalize_fda_calendar_entry(entry: dict, instrument_id: str) -> dict:
    meeting_date = entry["meeting_date"]
    return {
        "event_id": f"fda-{entry['ticker']}-{meeting_date}",
        "instrument_id": instrument_id,
        "ticker": entry["ticker"],
        "event_type": "advisory_committee",
        "release_timestamp": f"{meeting_date}T00:00:00",
        "timestamp_precision": "date_only",
        "session_label": "date_only",
        "aligned_trade_date": align_date_only(meeting_date),
        "priority": 1,
        "sentiment": "neutral",
        "materiality_score": 0.8,
        "confidence_score": 0.85,
        "source_tier": "official",
        "source": "fda_calendar",
        "catalyst": entry["title"],
    }
```

- [ ] **Step 5: Re-run the source-client tests until green**

Run: `pytest tests/test_sec_edgar_client.py tests/test_fda_calendar_client.py -q`

Expected: PASS

- [ ] **Step 6: Commit the official-source client layer**

```bash
git add src/tools/sec_edgar_client.py src/tools/fda_calendar_client.py tests/test_sec_edgar_client.py tests/test_fda_calendar_client.py
git commit -m "feat(ingestion): add SEC and FDA normalization clients"
```

### Task 4: Add RSS Normalization for Presswire and Biotech News Sources

**Files:**
- Create: `src/tools/rss_event_client.py`
- Create: `tests/test_rss_event_client.py`

- [ ] **Step 1: Write failing RSS normalization tests**

```python
def test_prnewswire_item_normalizes_to_presswire_event():
    from src.tools.rss_event_client import normalize_rss_item

    item = {
        "source": "prnewswire",
        "ticker": "SAGE",
        "published_at": "2026-04-22T07:15:00-04:00",
        "title": "Sage Therapeutics announces Phase 2 topline data",
    }

    row = normalize_rss_item(item, instrument_id="inst_sage")

    assert row["source_tier"] == "presswire"
    assert row["session_label"] == "premarket"
    assert row["event_type"] == "clinical_readout"
```

- [ ] **Step 2: Run the RSS tests and confirm failure**

Run: `pytest tests/test_rss_event_client.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement a single normalization helper with source-tier branching**

```python
def normalize_rss_item(item: dict, instrument_id: str) -> dict:
    source = item["source"]
    published_at = item["published_at"]
    if "phase" in item["title"].lower() or "topline" in item["title"].lower():
        event_type = "clinical_readout"
    else:
        event_type = "corporate_update"

    return {
        "event_id": f"{source}-{item['ticker']}-{published_at}",
        "instrument_id": instrument_id,
        "ticker": item["ticker"],
        "event_type": event_type,
        "release_timestamp": published_at,
        "timestamp_precision": "minute",
        "session_label": classify_session(published_at),
        "aligned_trade_date": align_trade_date(published_at),
        "priority": 2,
        "sentiment": "neutral",
        "materiality_score": 0.5,
        "confidence_score": 0.6,
        "source_tier": "presswire" if source in {"prnewswire", "globenewswire"} else "news",
        "source": source,
        "catalyst": item["title"],
    }
```

- [ ] **Step 4: Re-run the RSS tests until green**

Run: `pytest tests/test_rss_event_client.py -q`

Expected: PASS

- [ ] **Step 5: Commit the RSS normalization layer**

```bash
git add src/tools/rss_event_client.py tests/test_rss_event_client.py
git commit -m "feat(ingestion): add RSS normalization for biotech press sources"
```

### Task 5: Upgrade Event Ingestion Service to Use the New Schema and Source Tiers

**Files:**
- Modify: `src/services/event_ingestion_service.py`
- Modify: `tests/test_event_ingestion_service.py`

- [ ] **Step 1: Add failing ingestion tests for official + RSS source orchestration**

```python
def test_get_events_for_ticker_persists_official_and_press_sources(monkeypatch, tmp_path):
    from src.services.event_ingestion_service import get_events_for_ticker

    events = get_events_for_ticker("MRNA", max_age_hours=6)

    assert isinstance(events, list)
    assert all("aligned_trade_date" in row for row in events)
    assert any(row["source_tier"] == "official" for row in events)
```

- [ ] **Step 2: Run the ingestion test file and confirm failure**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: FAIL because the service still returns the old event shape.

- [ ] **Step 3: Change the service to ingest by source class, not by legacy event type**

```python
sources = [
    "clinicaltrials",
    "sec_edgar",
    "fda_calendar",
    "prnewswire",
    "globenewswire",
    "fiercebiotech",
]
```

Persist:
- normalized event rows to `biotech_events`
- raw payloads to `event_source_records`
- fetch attempts to `fetch_log`

- [ ] **Step 4: Keep `openfda` and `gdelt` as supplemental sources, not primary gatekeepers**

```python
supplemental_sources = ["openfda", "gdelt"]
```

Only ingest them if available; never require them for a green path.

- [ ] **Step 5: Re-run ingestion tests until green**

Run: `pytest tests/test_event_ingestion_service.py -q`

Expected: PASS

- [ ] **Step 6: Commit the ingestion-service rewrite**

```bash
git add src/services/event_ingestion_service.py tests/test_event_ingestion_service.py
git commit -m "feat(ingestion): orchestrate PIT-aware official and press sources"
```

## Day 2 Release Gate

Outcome: the K-Line route is now a biotech workspace with clear release-time vs tradable-time semantics and Source/Facts inspection panes.

### Task 6: Expand the Chart Contract to Carry Dual-Time Event Semantics

**Files:**
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/index.tsx`
- Modify: `tests/test_kline_chart_loader.py`

- [ ] **Step 1: Add a failing loader test for the new event fields**

```python
def test_chart_loader_requires_dual_time_event_fields():
    event = {
        "event_id": "evt_1",
        "ticker": "MRNA",
        "release_timestamp": "2026-04-22T16:35:00-04:00",
        "aligned_trade_date": "2026-04-23",
        "session_label": "after_close",
        "confidence_score": 0.85,
        "source_tier": "official",
    }

    assert event["aligned_trade_date"] == "2026-04-23"
```

- [ ] **Step 2: Run the chart-loader test file and confirm red coverage**

Run: `pytest tests/test_kline_chart_loader.py -q`

Expected: FAIL or missing assertions around new fields.

- [ ] **Step 3: Extend the TypeScript event shape**

```ts
export type BiotechEvent = {
  event_id: string;
  ticker: string;
  event_type: string;
  release_timestamp: string;
  aligned_trade_date: string;
  timestamp_precision: "minute" | "hour" | "date_only" | "unknown";
  session_label: "premarket" | "regular_session" | "after_close" | "date_only" | "unknown";
  confidence_score: number;
  source_tier: "official" | "presswire" | "news" | "supplemental";
  catalyst: string;
};
```

- [ ] **Step 4: Pass the new fields through the UMD entrypoint without transformation loss**

```ts
root.render(
  <CandlestickChart
    ohlcData={config.ohlcData}
    events={config.events}
    ...
  />
);
```

- [ ] **Step 5: Re-run the loader test and make it green**

Run: `pytest tests/test_kline_chart_loader.py -q`

Expected: PASS

- [ ] **Step 6: Commit the chart contract expansion**

```bash
git add src/kline/chart/types.ts src/kline/chart/index.tsx tests/test_kline_chart_loader.py
git commit -m "feat(kline): extend chart contract with dual-time biotech event fields"
```

### Task 7: Redesign the K-Line Workspace Shell Around Events, Source, Facts, and Backtest

**Files:**
- Modify: `templates/kline_report.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Add a failing integration test for the four-tab workspace**

```python
def test_kline_page_renders_events_source_facts_backtest_tabs(client):
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert 'data-tab="events"' in html
    assert 'data-tab="source"' in html
    assert 'data-tab="facts"' in html
    assert 'data-tab="backtest"' in html
```

- [ ] **Step 2: Run the K-Line web integration test and confirm failure**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: FAIL because `source` and `facts` tabs do not exist yet.

- [ ] **Step 3: Update the page shell to add the new tabs and dual-time labels**

```html
<button type="button" class="workspace-tab" data-tab="events">Events</button>
<button type="button" class="workspace-tab" data-tab="source">Source</button>
<button type="button" class="workspace-tab" data-tab="facts">Facts</button>
<button type="button" class="workspace-tab" data-tab="backtest">Backtest</button>
```

Add a top ribbon region:

```html
<div id="session-ribbon" class="session-ribbon">
  <span class="session-label">Release Timeline</span>
  <span id="release-session-summary"></span>
</div>
```

- [ ] **Step 4: Add deterministic empty states for Source and Facts panes**

```html
<div id="source-empty-state" class="empty-state">No source records loaded for this ticker.</div>
<div id="facts-empty-state" class="empty-state">No extracted facts are available yet.</div>
```

- [ ] **Step 5: Re-run the K-Line web integration test until green**

Run: `pytest tests/test_kline_web_integration.py -q`

Expected: PASS

- [ ] **Step 6: Commit the workspace shell redesign**

```bash
git add templates/kline_report.html tests/test_kline_web_integration.py
git commit -m "feat(kline): redesign workspace with source and facts panes"
```

### Task 8: Render Biotech Particle Semantics Instead of Generic Event Dots

**Files:**
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Modify: `tests/test_chart_rendering.py`

- [ ] **Step 1: Add a failing rendering test for session-aware particle semantics**

```python
def test_chart_payload_supports_session_and_confidence_fields():
    event = {
        "event_type": "clinical_readout",
        "session_label": "after_close",
        "source_tier": "official",
        "confidence_score": 0.92,
    }

    assert event["source_tier"] == "official"
```

- [ ] **Step 2: Run the chart rendering tests and confirm failure or missing assertions**

Run: `pytest tests/test_chart_rendering.py -q`

Expected: red coverage for the new semantics.

- [ ] **Step 3: Add deterministic particle encoding helpers**

```ts
function eventColor(event: BiotechEvent): string {
  if (event.event_type === "clinical_readout") return "#00e5ff";
  if (event.event_type === "advisory_committee") return "#00e676";
  if (event.event_type === "safety_signal") return "#ff5252";
  return "#667eea";
}

function eventOpacity(event: BiotechEvent): number {
  return Math.max(0.2, Math.min(1, event.confidence_score));
}
```

- [ ] **Step 4: Add release-to-trade awareness in the tooltip payload**

```ts
tooltip.innerHTML = `
  <strong>${event.catalyst}</strong>
  <div>Release: ${event.release_timestamp}</div>
  <div>Tradable: ${event.aligned_trade_date}</div>
  <div>Session: ${event.session_label}</div>
  <div>Source tier: ${event.source_tier}</div>
`;
```

- [ ] **Step 5: Re-run the chart rendering tests until green**

Run: `pytest tests/test_chart_rendering.py -q`

Expected: PASS

- [ ] **Step 6: Commit the chart semantic upgrade**

```bash
git add src/kline/chart/CandlestickChart.tsx tests/test_chart_rendering.py
git commit -m "feat(kline): render biotech particle semantics and dual-time tooltips"
```

## Day 3 Release Gate

Outcome: backtest execution uses explicit, conservative alignment and exposes its assumptions in the API response.

### Task 9: Gate Signal Eligibility by Precision, Confidence, and Source Tier

**Files:**
- Modify: `src/backtest/signals.py`
- Create: `tests/test_backtest_execution_rules.py`

- [ ] **Step 1: Write failing signal-eligibility tests**

```python
def test_generate_signals_filters_low_confidence_events():
    import pandas as pd
    from src.backtest.signals import generate_signals

    ohlc = pd.DataFrame({"date": ["2026-04-23"], "open": [10], "high": [11], "low": [9], "close": [10.5], "volume": [1000]})
    events = pd.DataFrame([
        {
            "aligned_trade_date": "2026-04-23",
            "event_type": "clinical_readout",
            "priority": 1,
            "sentiment": "positive",
            "confidence_score": 0.2,
            "timestamp_precision": "minute",
            "source_tier": "official",
        }
    ])

    signals = generate_signals(ohlc, events)
    assert int(signals.iloc[0]["signal"]) == 0
```

- [ ] **Step 2: Run the backtest execution rules test and confirm failure**

Run: `pytest tests/test_backtest_execution_rules.py -q`

Expected: FAIL because `generate_signals()` still only uses date/type/priority/sentiment.

- [ ] **Step 3: Add a trade-eligibility predicate to `signals.py`**

```python
def is_trade_eligible(event: dict) -> bool:
    if float(event.get("confidence_score", 0.0)) < 0.6:
        return False
    if event.get("timestamp_precision") in {"unknown"}:
        return False
    if event.get("source_tier") not in {"official", "presswire"}:
        return False
    return True
```

- [ ] **Step 4: Update `generate_signals()` to use `aligned_trade_date`**

```python
ev["date"] = pd.to_datetime(ev["aligned_trade_date"])
ev = ev[ev.apply(is_trade_eligible, axis=1)]
```

- [ ] **Step 5: Re-run the execution-rules tests until green**

Run: `pytest tests/test_backtest_execution_rules.py -q`

Expected: PASS

- [ ] **Step 6: Commit the signal gating**

```bash
git add src/backtest/signals.py tests/test_backtest_execution_rules.py
git commit -m "feat(backtest): gate signals by confidence precision and source tier"
```

### Task 10: Add Conservative Execution Rules and Slippage Multipliers to the Runner

**Files:**
- Modify: `src/backtest/runner.py`
- Modify: `tests/test_backtest_runner.py`
- Modify: `tests/test_backtest_api.py`

- [ ] **Step 1: Write failing runner tests for execution audit and slippage multipliers**

```python
def test_run_kline_backtest_returns_execution_audit():
    from src.backtest.runner import run_kline_backtest

    result = run_kline_backtest("MRNA", "2026-01-01", "2026-12-31")

    assert "execution_audit" in result
    assert "bias_warnings" in result
```

- [ ] **Step 2: Run the runner and API tests and confirm failure**

Run: `pytest tests/test_backtest_runner.py tests/test_backtest_api.py -q`

Expected: FAIL because these fields are not returned yet.

- [ ] **Step 3: Add a deterministic slippage helper in the runner**

```python
def _effective_slippage(event_type: str, session_label: str, gap_pct: float, base: float) -> float:
    event_mult = 1.8 if event_type in {"clinical_readout", "fda_decision", "safety_signal"} else 1.2
    session_mult = 1.5 if session_label in {"premarket", "after_close"} else 1.0
    gap_mult = 1.5 if abs(gap_pct) >= 0.10 else 1.0
    return round(base * event_mult * session_mult * gap_mult, 6)
```

- [ ] **Step 4: Return an execution audit payload**

```python
payload["execution_audit"] = [
    {
        "event_id": row["event_id"],
        "release_timestamp": row["release_timestamp"],
        "aligned_trade_date": row["aligned_trade_date"],
        "session_label": row["session_label"],
        "execution_rule": "next_tradable_open",
    }
    for _, row in events.iterrows()
]
payload["bias_warnings"] = [
    "Universe may remain survivorship-biased.",
    "Expectation proxy is incomplete; IV and analyst consensus are not modeled.",
    "Intraday microstructure is not simulated; execution is modeled conservatively at the next tradable open.",
]
```

- [ ] **Step 5: Re-run the runner and API tests until green**

Run: `pytest tests/test_backtest_runner.py tests/test_backtest_api.py -q`

Expected: PASS

- [ ] **Step 6: Commit the conservative execution model**

```bash
git add src/backtest/runner.py tests/test_backtest_runner.py tests/test_backtest_api.py
git commit -m "feat(backtest): add execution audit and conservative slippage model"
```

## Day 4 Release Gate

Outcome: disease survey reports delete `Sponsor Analysis`, replace `Safety Profile` with a concise sponsor technical-route summary, upgrade `Market Landscape` into a clinical-timing plus competition chapter, and tighten `CNS Benchmark` to a top-50-journal / last-5-years evidence scope.

### Task 11: Replace `Sponsor Analysis` and `Safety Profile` with a Summary-Oriented `Technical Route Summary`

**Files:**
- Create: `src/tools/company_approach_client.py`
- Create: `src/engines/report_engine/disease_survey/technical_route.py`
- Modify: `src/engines/report_engine/disease_survey/models.py`
- Modify: `src/engines/report_engine/disease_survey/renderer.py`
- Modify: `src/engines/report_engine/disease_survey/composer.py`
- Modify: `src/engines/report_engine/disease_survey/__init__.py`

- [ ] **Step 1: Crawl and normalize each sponsor's official technical-route page**

Prefer source order:
- official sponsor website `Science` / `Our Approach` / `Platform` / `Our Story`
- official pipeline page on the same domain
- investor presentation or annual filing only if the website lacks route detail

For each sponsor, capture:
- `company_name`
- `asset_name`
- `modality`
- `target`
- `platform_summary`
- `delivery_strategy`
- `biomarker_or_patient_selection`
- `source_url`
- `source_title`

- [ ] **Step 2: Replace the old empty safety section with a deterministic summary table**

Render one row per company or lead asset with these columns:
- `Company`
- `Lead Asset / Program`
- `Technical Route`
- `Why This Route Fits The Disease`
- `Evidence Source`

Day 4 note:
- do not use a failing-test-first workflow in this chapter plan
- do not add a standalone probability model
- do not ask the LLM for a subjective success prediction

This section is a summary chapter. It should explain each company's route in plain language and cite the official source page used.

- [ ] **Step 3: Remove `Sponsor Analysis` and rename the section everywhere**

Use this section name everywhere:
- payload key: `technical_route_summary`
- display title: `Technical Route Summary`

Update the composer order to:
- `Executive Summary`
- `Drug Pipeline`
- `Trial Landscape`
- `Target Biology`
- `Technical Route Summary`
- `Literature Review`
- `CNS Benchmark`
- `Market Landscape`

- [ ] **Step 4: Keep Day 4 implementation lightweight and summary-oriented**

Implementation emphasis:
- renderer / composer output quality
- source attribution
- concise structured summaries

Not in scope for this task:
- subjective feasibility scores
- probabilistic risk bands
- a separate exploratory prediction module

### Task 12: Upgrade `Market Landscape` into an Objective Competition Summary

**Files:**
- Create: `src/engines/report_engine/disease_survey/market_landscape_analysis.py`
- Modify: `src/engines/report_engine/disease_survey/models.py`
- Modify: `src/engines/report_engine/disease_survey/aggregator.py`
- Modify: `src/engines/report_engine/disease_survey/renderer.py`
- Modify: `src/engines/report_engine/disease_survey/composer.py`
- Modify: `src/engines/report_engine/disease_survey/__init__.py`

- [ ] **Step 1: Preserve timing fields already harvested from ClinicalTrials.gov**

Carry these fields through `TrialRecord` and aggregation:
- `start_date`
- `primary_completion_date`
- `completion_date`
- `results_first_posted`

Do not add a new upstream ClinicalTrials.gov fetcher here. The existing client already exposes these dates.

- [ ] **Step 2: Split `Market Landscape` into two summary tables**

Table A: `Clinical Timing`
- `Asset`
- `Company`
- `Phase 2 Start`
- `Phase 2 Primary Completion`
- `Phase 3 Start`
- `Phase 2 -> Phase 3 Gap`
- `Timing Observation`

Table B: `Competitive Market`
- `Asset`
- `Company`
- `Phase`
- `Target / Class`
- `Competition Bucket`
- `Share Basis`
- `Actual Share` or `Projected Position`
- `Source`

- [ ] **Step 3: Keep the market analysis objective rather than predictive**

Use these rules:
- if `Phase 2 -> Phase 3` takes more than `36 months`, flag it as a long interval
- if the interval is `60+ months`, flag it as a very long interval
- if a product is approved and the sponsor discloses indication-level revenue, show `actual` share
- if a product is not approved or revenue is unavailable, show `projected position` / `competition bucket`, not a fabricated market-share percentage
- group same-disease, same-target, same-modality, or same-milestone-window assets into the same competitive bucket

This chapter should answer:
- who is already commercialized
- who is late-stage and approaching the market
- which programs are likely competing for the same patient pool
- whether long development gaps imply weaker execution or higher timeline risk

- [ ] **Step 4: Keep the output as a report chapter, not a prediction engine**

Do:
- summarize current market structure
- separate realized share from projected competition
- explain what the timing gaps mean in business terms

Do not:
- output a modeled probability of success
- output synthetic market-share percentages for pre-revenue assets
- over-fit the section into a scoring framework

### Task 13: Tighten `CNS Benchmark` Retrieval to Top-50 Journals in the Last Five Years

**Files:**
- Modify: `src/tools/pubmed_client.py`
- Modify: `src/engines/harvest/llm/prompts.py`
- Modify: `src/prompts/bioharvest/query_generation.txt`
- Modify: `src/engines/report_engine/disease_survey/aggregator.py`
- Modify: `src/engines/report_engine/disease_survey/renderer.py`
- Modify: `src/engines/report_engine/disease_survey/composer.py`

- [ ] **Step 1: Stop relying on the raw user query alone**

Strengthen `CNS Benchmark` query generation with:
- disease name
- disease synonyms
- target synonyms
- mechanism / pathway terms
- modality terms
- benchmark intent words such as `landscape`, `review`, `clinical`, `translational`, `biomarker`

The benchmark search prompt should expand the query automatically instead of passing through only what the user typed.

- [ ] **Step 2: Hard-limit the evidence scope**

For `CNS Benchmark`, only retrieve or keep:
- publications from the last `5 years`
- publications in the predefined `top 50` journal whitelist

This same scope applies to:
- online retrieval
- local storage / caching
- report rendering

- [ ] **Step 3: Make the benchmark section transparent about what it searched**

Render or store:
- `search_queries_used`
- `journal_scope = top_50_only`
- `year_scope = last_5_years`
- `top50_journal_hits`
- `matched_targets`

This makes it clear why the benchmark is narrower and higher quality than the current broad search.

- [ ] **Step 4: Keep the section focused on benchmark evidence, not literature volume for its own sake**

The purpose of this section is:
- compare the disease's major targets or mechanisms against a curated CNS evidence set
- surface whether the current pipeline is aligned with the strongest recent literature
- avoid noisy long-tail journals and stale historical records

## Self-Review

### 1. Spec Coverage

- Day 1 schema + source layering: covered by Tasks 1-5
- Day 2 K-Line biotech workspace and dual-time semantics: covered by Tasks 6-8
- Day 3 backtest alignment and credibility: covered by Tasks 9-10
- Day 4 sponsor/safety replacement, market-intelligence summary, and CNS benchmark tightening: covered by Tasks 11-13

No spec sections are intentionally left without at least one task. The slot/handoff writer refactor is explicitly deferred by design.

### 2. Placeholder Scan

Checked for:
- `TODO`
- `TBD`
- “implement later”
- “add appropriate error handling”
- “write tests for the above”

None are used as task placeholders. Every task includes file paths plus explicit output rules, scope boundaries, or implementation constraints.

### 3. Type Consistency

Key names kept consistent across tasks:
- `release_timestamp`
- `aligned_trade_date`
- `timestamp_precision`
- `session_label`
- `confidence_score`
- `source_tier`
- `technical_route_summary`
- `phase2_to_phase3_gap_months`
- `share_basis`
- `actual_share_pct`
- `projected_share_bucket`
- `search_queries_used`
- `top50_journal_hits`

No later task renames these contracts.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-22-biotech-research-stack-v1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
