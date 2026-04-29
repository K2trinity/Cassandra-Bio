# Kline Phase 2.1 Data Truth Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent cached or mis-scoped event data from polluting Kline workspaces and backtests while adding trusted macro context and saved backtest visibility.

**Architecture:** Add a trust/provenance boundary between raw event ingestion and Kline/backtest consumers. Raw cache rows remain auditable, but workspace and backtest paths consume only trusted, ticker-scoped, schema-versioned projections.

**Tech Stack:** Python 3.11, Flask, SQLite, pandas, pytest, Vite/TypeScript Kline chart bundle.

---

## File Structure

- Modify `src/backtest/events_db.py`
  - Add trust/provenance columns.
  - Add trusted read functions and legacy quarantine helpers.
  - Keep raw reads available for audit.
- Create `src/kline/event_trust.py`
  - Central constants, query hash/source run helpers, trust decoration, and metadata decoding.
- Modify `src/services/event_ingestion_service.py`
  - Generate source run ids.
  - Apply trust metadata before insert.
  - Return trusted events only.
  - Add `macro_regime` source.
- Modify `src/tools/clinical_trials_client.py`
  - Allow unowned trial rows to be emitted for quarantine when requested.
  - Preserve ownership evidence in metadata.
- Create `src/tools/macro_regime_client.py`
  - Build structured macro events from benchmark OHLC fixtures/cache.
- Modify `src/backtest/runner.py`
  - Use trusted event reads.
  - Write latest-run index.
  - Add trust/source summaries to payload.
- Modify `src/kline/providers/backtest_provider.py`
  - Load latest indexed backtest run by ticker.
- Modify `src/kline/models.py`, `src/kline/providers/catalyst_provider.py`, `static/kline/workspace.js`, `src/kline/chart/types.ts`
  - Carry trust/provenance fields to UI details and chart payloads.
- Add tests:
  - `tests/test_kline_event_trust_db.py`
  - `tests/test_event_ingestion_trust_boundary.py`
  - `tests/test_macro_regime_client.py`
  - `tests/test_kline_backtest_trusted_inputs.py`
  - Extend existing Kline workspace/JS/backtest tests.

---

## Task 1: Event Trust Schema and Trusted Repository

**Files:**
- Create: `src/kline/event_trust.py`
- Modify: `src/backtest/events_db.py`
- Test: `tests/test_kline_event_trust_db.py`

- [ ] **Step 1: Write failing trusted repository tests**

Create `tests/test_kline_event_trust_db.py`:

```python
import sqlite3

from src.backtest import events_db


def use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(events_db, "DB_PATH", db_path)
    events_db.init_db()
    return db_path


def test_legacy_rows_are_excluded_from_trusted_chart_reads(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    events_db.insert_event(
        {
            "id": "legacy-mrna",
            "date": "2025-01-01",
            "type": "clinical_readout",
            "priority": 1,
            "ticker": "MRNA",
            "disease_area": "Oncology",
            "catalyst": "Legacy RNA title match",
            "sentiment": "positive",
            "source": "clinicaltrials",
        }
    )

    assert events_db.get_events_for_chart("MRNA")
    assert events_db.get_trusted_events_for_chart("MRNA") == []


def test_trusted_reads_require_ticker_scope_and_schema_version(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    trusted = {
        "id": "trusted-mrna",
        "date": "2025-02-01",
        "type": "trial_results_posted",
        "priority": 1,
        "ticker": "MRNA",
        "ticker_scope": "MRNA",
        "disease_area": "Oncology",
        "catalyst": "Moderna owned readout",
        "sentiment": "positive",
        "source": "clinicaltrials",
        "source_run_id": "clinicaltrials-MRNA-20260429",
        "query_hash": "abc123",
        "company_identity": "MRNA|Moderna, Inc.",
        "ownership_status": "owned",
        "trust_status": "trusted",
        "schema_version": 2,
        "quarantine_reason": None,
        "metadata": {"backtest_eligible": True},
    }
    wrong_scope = dict(trusted, id="wrong-scope", ticker="MRNA", ticker_scope="BNTX")
    old_schema = dict(trusted, id="old-schema", schema_version=1)
    quarantined = dict(
        trusted,
        id="quarantined",
        trust_status="quarantined",
        quarantine_reason="unowned clinical trial",
    )

    events_db.insert_events([trusted, wrong_scope, old_schema, quarantined])

    events = events_db.get_trusted_events_for_chart("MRNA")
    assert [event["id"] for event in events] == ["trusted-mrna"]


def test_trusted_backtest_reads_require_backtest_eligible(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    base = {
        "date": "2025-03-01",
        "type": "trial_results_posted",
        "priority": 1,
        "ticker": "MRNA",
        "ticker_scope": "MRNA",
        "disease_area": "Oncology",
        "catalyst": "Readout",
        "sentiment": "positive",
        "source": "clinicaltrials",
        "source_run_id": "run-1",
        "query_hash": "hash-1",
        "company_identity": "MRNA|Moderna, Inc.",
        "ownership_status": "owned",
        "trust_status": "trusted",
        "schema_version": 2,
    }
    events_db.insert_events(
        [
            dict(base, id="eligible", metadata={"backtest_eligible": True}),
            dict(base, id="visual-only", metadata={"backtest_eligible": False}),
        ]
    )

    events = events_db.get_trusted_events_for_backtest(
        "MRNA", start_date="2025-01-01", end_date="2025-12-31"
    )
    assert list(events["id"]) == ["eligible"]


def test_mark_legacy_events_untrusted_updates_missing_schema(monkeypatch, tmp_path):
    db_path = use_temp_db(monkeypatch, tmp_path)
    events_db.insert_event(
        {
            "id": "legacy-row",
            "date": "2025-01-01",
            "type": "market_news",
            "priority": 3,
            "ticker": "MRNA",
            "disease_area": "",
            "catalyst": "Old row",
            "sentiment": "neutral",
            "source": "alphavantage",
        }
    )

    updated = events_db.mark_legacy_events_untrusted("MRNA")

    assert updated == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT trust_status, schema_version FROM biotech_events WHERE id = ?",
            ("legacy-row",),
        ).fetchone()
    assert row == ("legacy_untrusted", 1)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_kline_event_trust_db.py -q
```

Expected: FAIL because `get_trusted_events_for_chart`, `get_trusted_events_for_backtest`, and `mark_legacy_events_untrusted` do not exist yet.

- [ ] **Step 3: Implement `src/kline/event_trust.py`**

Create `src/kline/event_trust.py`:

```python
"""Trust and provenance helpers for Kline event ingestion."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import uuid
from typing import Any

TRUSTED_SCHEMA_VERSION = 2
TRUSTED_STATUSES = {"trusted"}
TRUSTED_OWNERSHIP_STATUSES = {"owned", "market_relevant", "macro_context"}
BACKTEST_TRUSTED_OWNERSHIP_STATUSES = {"owned", "market_relevant", "macro_context"}


def decode_metadata(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def build_source_run_id(ticker: str, source: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{source}:{str(ticker).strip().upper()}:{timestamp}:{suffix}"


def build_query_hash(source: str, ticker: str, params: dict[str, Any] | None = None) -> str:
    payload = {
        "source": str(source or "").strip().lower(),
        "ticker": str(ticker or "").strip().upper(),
        "params": params or {},
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def apply_event_trust(
    event: dict[str, Any],
    *,
    ticker: str,
    source: str,
    source_run_id: str,
    query_hash: str,
    company_identity: str,
    ownership_status: str,
    trust_status: str = "trusted",
    quarantine_reason: str | None = None,
) -> dict[str, Any]:
    normalized = dict(event)
    normalized["ticker"] = str(ticker).strip().upper()
    normalized["ticker_scope"] = str(ticker).strip().upper()
    normalized["source"] = source
    normalized["source_run_id"] = source_run_id
    normalized["query_hash"] = query_hash
    normalized["company_identity"] = company_identity
    normalized["ownership_status"] = ownership_status
    normalized["trust_status"] = trust_status
    normalized["schema_version"] = TRUSTED_SCHEMA_VERSION
    normalized["quarantine_reason"] = quarantine_reason
    metadata = decode_metadata(normalized.get("metadata"))
    metadata.update(
        {
            "ticker_scope": normalized["ticker_scope"],
            "source_run_id": source_run_id,
            "query_hash": query_hash,
            "company_identity": company_identity,
            "ownership_status": ownership_status,
            "trust_status": trust_status,
            "schema_version": TRUSTED_SCHEMA_VERSION,
        }
    )
    if quarantine_reason:
        metadata["quarantine_reason"] = quarantine_reason
    normalized["metadata"] = metadata
    return normalized


def is_metadata_backtest_eligible(value: object) -> bool:
    metadata = decode_metadata(value)
    raw = metadata.get("backtest_eligible")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes", "y"}
    return bool(raw)
```

- [ ] **Step 4: Implement trust columns and trusted reads in `events_db.py`**

Add event column definitions:

```python
EVENT_TRUST_COLUMN_DEFINITIONS = {
    "ticker_scope": "TEXT",
    "source_run_id": "TEXT",
    "query_hash": "TEXT",
    "company_identity": "TEXT",
    "ownership_status": "TEXT DEFAULT 'unknown'",
    "trust_status": "TEXT DEFAULT 'legacy_untrusted'",
    "schema_version": "INTEGER DEFAULT 1",
    "quarantine_reason": "TEXT",
}
```

Merge this dictionary into `_ensure_columns()` after existing attribution columns. Update `_serialize_event()` so missing trust fields default to legacy-untrusted:

```python
serialized.setdefault("ticker_scope", serialized.get("ticker"))
serialized.setdefault("source_run_id", None)
serialized.setdefault("query_hash", None)
serialized.setdefault("company_identity", None)
serialized.setdefault("ownership_status", "unknown")
serialized.setdefault("trust_status", "legacy_untrusted")
serialized.setdefault("schema_version", 1)
serialized.setdefault("quarantine_reason", None)
```

Update `insert_event()` and `insert_events()` column lists to include:

```python
ticker_scope, source_run_id, query_hash, company_identity,
ownership_status, trust_status, schema_version, quarantine_reason
```

Add trusted read helpers:

```python
def get_trusted_events_for_chart(ticker: str) -> list[dict]:
    init_db()
    conn = _get_conn()
    query = """
        SELECT * FROM biotech_events
        WHERE ticker_scope = ?
          AND trust_status = 'trusted'
          AND schema_version >= 2
          AND ownership_status IN ('owned', 'market_relevant', 'macro_context')
        ORDER BY date
    """
    rows = [dict(row) for row in conn.execute(query, (ticker.upper(),)).fetchall()]
    conn.close()
    return [_decode_event_row(row) for row in rows]


def get_trusted_events_for_backtest(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    init_db()
    conn = _get_conn()
    query = """
        SELECT * FROM biotech_events
        WHERE ticker_scope = ?
          AND trust_status = 'trusted'
          AND schema_version >= 2
          AND ownership_status IN ('owned', 'market_relevant', 'macro_context')
    """
    params: list[object] = [ticker.upper()]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if df.empty:
        return df
    df["metadata"] = df["metadata"].apply(lambda value: _decode_json_field(value, {}, dict))
    return df[df["metadata"].apply(lambda metadata: bool(metadata.get("backtest_eligible")))].reset_index(drop=True)


def mark_legacy_events_untrusted(ticker: str | None = None) -> int:
    init_db()
    conn = _get_conn()
    if ticker:
        cur = conn.execute(
            """
            UPDATE biotech_events
            SET trust_status = 'legacy_untrusted',
                schema_version = COALESCE(schema_version, 1),
                quarantine_reason = COALESCE(quarantine_reason, 'legacy row missing trust provenance')
            WHERE ticker = ?
              AND (schema_version IS NULL OR schema_version < 2 OR trust_status IS NULL)
            """,
            (ticker.upper(),),
        )
    else:
        cur = conn.execute(
            """
            UPDATE biotech_events
            SET trust_status = 'legacy_untrusted',
                schema_version = COALESCE(schema_version, 1),
                quarantine_reason = COALESCE(quarantine_reason, 'legacy row missing trust provenance')
            WHERE schema_version IS NULL OR schema_version < 2 OR trust_status IS NULL
            """
        )
    conn.commit()
    count = cur.rowcount
    conn.close()
    return int(count or 0)
```

- [ ] **Step 5: Run GREEN verification**

Run:

```bash
pytest tests/test_kline_event_trust_db.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/kline/event_trust.py src/backtest/events_db.py tests/test_kline_event_trust_db.py
git commit -m "feat(kline): add trusted event repository"
```

---

## Task 2: Ingestion Trust Boundary and Clinical Ownership Quarantine

**Files:**
- Modify: `src/services/event_ingestion_service.py`
- Modify: `src/tools/clinical_trials_client.py`
- Test: `tests/test_event_ingestion_trust_boundary.py`
- Test: `tests/test_event_ingestion_service.py`

- [ ] **Step 1: Write failing ingestion trust tests**

Create `tests/test_event_ingestion_trust_boundary.py`:

```python
from src.backtest import events_db
from src.services import event_ingestion_service


def use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(events_db, "DB_PATH", tmp_path / "events.db")
    events_db.init_db()
    events_db.init_fetch_log_table()


def test_ingestion_returns_only_trusted_events(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    events_db.insert_event(
        {
            "id": "old-mrna",
            "date": "2025-01-01",
            "type": "clinical_readout",
            "priority": 1,
            "ticker": "MRNA",
            "disease_area": "",
            "catalyst": "Old RNA-only row",
            "sentiment": "positive",
            "source": "clinicaltrials",
        }
    )
    monkeypatch.setattr(event_ingestion_service, "search_trials", lambda *args, **kwargs: [])
    monkeypatch.setattr(event_ingestion_service, "fetch_market_news_events", lambda ticker: ([], {"status": "disabled", "message": "no key"}))
    monkeypatch.setattr(event_ingestion_service, "fetch_biotech_macro_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(event_ingestion_service, "fetch_macro_regime_events", lambda *args, **kwargs: [])

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events == []
    statuses = {row["source"]: row["status"] for row in events_db.get_fetch_log_entries("MRNA")}
    assert statuses["clinicaltrials"] == "empty"
    assert statuses["alphavantage"] == "disabled"


def test_unowned_clinical_trial_is_quarantined_not_returned(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    trial = {
        "nct_id": "NCT12345678",
        "title": "RNA biomarker monitoring in glioblastoma",
        "sponsor": "University Research Center",
        "collaborators": [],
        "phase": "PHASE2",
        "status": "COMPLETED",
        "completion_date": "2025-01-02",
        "primary_completion_date": "2025-01-01",
        "last_update_posted": "2025-01-03",
    }
    monkeypatch.setattr(event_ingestion_service, "search_trials", lambda *args, **kwargs: [trial])
    monkeypatch.setattr(event_ingestion_service, "fetch_market_news_events", lambda ticker: ([], {"status": "disabled", "message": "no key"}))
    monkeypatch.setattr(event_ingestion_service, "fetch_biotech_macro_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(event_ingestion_service, "fetch_macro_regime_events", lambda *args, **kwargs: [])

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events == []
    raw = events_db.get_events("MRNA")
    assert set(raw["trust_status"]) == {"quarantined"}
    assert set(raw["ownership_status"]) == {"unowned"}


def test_owned_clinical_trial_becomes_trusted(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    trial = {
        "nct_id": "NCT87654321",
        "title": "Moderna oncology vaccine study",
        "sponsor": "ModernaTX, Inc.",
        "collaborators": [],
        "phase": "PHASE2",
        "status": "COMPLETED",
        "completion_date": "2025-04-02",
        "primary_completion_date": "2025-04-01",
        "last_update_posted": "2025-04-03",
    }
    monkeypatch.setattr(event_ingestion_service, "search_trials", lambda *args, **kwargs: [trial])
    monkeypatch.setattr(event_ingestion_service, "fetch_market_news_events", lambda ticker: ([], {"status": "disabled", "message": "no key"}))
    monkeypatch.setattr(event_ingestion_service, "fetch_biotech_macro_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(event_ingestion_service, "fetch_macro_regime_events", lambda *args, **kwargs: [])

    events = event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=0)

    assert events
    assert {event["ticker_scope"] for event in events} == {"MRNA"}
    assert {event["trust_status"] for event in events} == {"trusted"}
    assert {event["ownership_status"] for event in events} == {"owned"}
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_event_ingestion_trust_boundary.py -q
```

Expected: FAIL because ingestion does not yet write trust fields or return trusted reads.

- [ ] **Step 3: Update `clinical_trials_client.py` to emit quarantinable unowned rows**

Change `normalize_clinical_trial_milestone_events()` signature:

```python
def normalize_clinical_trial_milestone_events(
    trials: List[Dict[str, Any]],
    source: str = "clinicaltrials",
    requested_ticker: str | None = None,
    include_unowned: bool = False,
) -> List[Dict[str, Any]]:
```

Replace the current ownership skip block with:

```python
entity_match = _clinical_ownership_match(trial, requested_ticker, sponsor)
is_unowned_requested_trial = requested_ticker is not None and entity_match is None
if is_unowned_requested_trial and not include_unowned:
    logger.debug(
        "Skipping ClinicalTrials milestone event without ticker ownership: "
        f"{requested_ticker}/{trial.get('nct_id')}"
    )
    continue
```

When building metadata, set:

```python
metadata = {
    "phase": phase,
    "status": status,
    "has_results": _to_bool(trial.get("has_results")),
    "interventions": interventions,
    "entity_match": entity_match or "",
    "ownership_status": "unowned" if is_unowned_requested_trial else "owned",
    "raw_type": event_type,
}
if is_unowned_requested_trial:
    metadata["quarantine_reason"] = "clinical trial sponsor/collaborator did not match requested ticker"
```

- [ ] **Step 4: Update `event_ingestion_service.py` to apply trust**

Import helpers:

```python
from src.kline.event_trust import (
    apply_event_trust,
    build_query_hash,
    build_source_run_id,
    decode_metadata,
)
from src.kline.ticker_resolver import TickerResolver
from src.tools.macro_regime_client import fetch_macro_regime_events
```

Add helper functions:

```python
def _company_identity(ticker: str) -> str:
    try:
        company = TickerResolver().resolve(ticker)
        return f"{company.ticker}|{company.name}"
    except ValueError:
        return f"{ticker.upper()}|{ticker.upper()}"


def _ownership_for_event(event: dict, source: str) -> tuple[str, str, str | None]:
    metadata = decode_metadata(event.get("metadata"))
    if source == "clinicaltrials":
        if metadata.get("ownership_status") == "unowned":
            return "unowned", "quarantined", metadata.get("quarantine_reason") or "unowned clinical trial"
        return "owned", "trusted", None
    if source == "openfda":
        return "market_relevant", "trusted", None
    if source in {"alphavantage", "gdelt"}:
        return "market_relevant", "trusted", None
    if source == "macro_regime":
        return "macro_context", "trusted", None
    return "unknown", "quarantined", "unknown event source"


def _enrich_events(
    events: list[dict],
    *,
    ticker: str,
    source: str,
    source_run_id: str,
    query_hash: str,
) -> list[dict]:
    company_identity = _company_identity(ticker)
    enriched = []
    for event in events:
        scored = enrich_event_metadata(event)
        ownership_status, trust_status, quarantine_reason = _ownership_for_event(scored, source)
        enriched.append(
            apply_event_trust(
                scored,
                ticker=ticker,
                source=source,
                source_run_id=source_run_id,
                query_hash=query_hash,
                company_identity=company_identity,
                ownership_status=ownership_status,
                trust_status=trust_status,
                quarantine_reason=quarantine_reason,
            )
        )
    return enriched
```

Inside the source loop, generate provenance before fetching:

```python
source_run_id = build_source_run_id(ticker, source)
query_hash = build_query_hash(source, ticker, {"max_age_hours": max_age_hours})
```

For clinical trials, call:

```python
events = normalize_clinical_trial_milestone_events(
    trials,
    source="clinicaltrials",
    requested_ticker=ticker,
    include_unowned=True,
)
```

For each source branch, replace `_enrich_events(events)` with:

```python
events = _enrich_events(
    events,
    ticker=ticker,
    source=source,
    source_run_id=source_run_id,
    query_hash=query_hash,
)
```

At the end of `get_events_for_ticker()`, return:

```python
return get_trusted_events_for_chart(ticker)
```

- [ ] **Step 5: Run GREEN verification**

Run:

```bash
pytest tests/test_event_ingestion_trust_boundary.py tests/test_event_ingestion_service.py tests/test_kline_event_filter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/services/event_ingestion_service.py src/tools/clinical_trials_client.py tests/test_event_ingestion_trust_boundary.py tests/test_event_ingestion_service.py
git commit -m "feat(kline): enforce ingestion trust boundary"
```

---

## Task 3: Structured Macro Regime Source

**Files:**
- Create: `src/tools/macro_regime_client.py`
- Modify: `src/services/event_ingestion_service.py`
- Test: `tests/test_macro_regime_client.py`
- Extend: `tests/test_event_ingestion_trust_boundary.py`

- [ ] **Step 1: Write failing macro regime tests**

Create `tests/test_macro_regime_client.py`:

```python
import pandas as pd

from src.tools.macro_regime_client import build_macro_regime_events


def frame(closes):
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_builds_sector_underperformance_event_from_xbi_vs_spy():
    events = build_macro_regime_events(
        ticker="MRNA",
        benchmark_frames={
            "XBI": frame([100, 98, 96, 93, 90]),
            "SPY": frame([100, 101, 102, 103, 104]),
        },
    )

    assert len(events) == 1
    event = events[0]
    assert event["source"] == "macro_regime"
    assert event["type"] == "sector_underperformance"
    assert event["ticker"] == "MRNA"
    assert event["sentiment"] == "negative"
    assert event["metadata"]["benchmark"] == "XBI"
    assert event["metadata"]["backtest_eligible"] is True


def test_builds_vix_risk_off_event_when_vix_is_elevated():
    events = build_macro_regime_events(
        ticker="MRNA",
        benchmark_frames={
            "^VIX": frame([15, 18, 22, 27, 31]),
        },
    )

    assert [event["type"] for event in events] == ["macro_risk_off"]
    assert events[0]["priority"] == 2
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_macro_regime_client.py -q
```

Expected: FAIL because `src.tools.macro_regime_client` does not exist.

- [ ] **Step 3: Implement `macro_regime_client.py`**

Create `src/tools/macro_regime_client.py`:

```python
"""Structured macro regime events for Kline."""

from __future__ import annotations

import uuid
from typing import Callable

import pandas as pd

from src.backtest.data_loader import load_ohlc

BENCHMARKS = ("XBI", "IBB", "SPY", "TLT", "^VIX")


def _latest_date(df: pd.DataFrame) -> str:
    return pd.to_datetime(df["date"].iloc[-1]).strftime("%Y-%m-%d")


def _window_return(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    first = float(df["close"].iloc[0])
    last = float(df["close"].iloc[-1])
    return 0.0 if first == 0 else last / first - 1


def _event_id(ticker: str, event_type: str, date: str, basis: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ticker}|{event_type}|{date}|{basis}"))


def build_macro_regime_events(
    ticker: str,
    benchmark_frames: dict[str, pd.DataFrame],
) -> list[dict]:
    events: list[dict] = []
    ticker = ticker.strip().upper()

    spy = benchmark_frames.get("SPY")
    spy_ret = _window_return(spy) if isinstance(spy, pd.DataFrame) and not spy.empty else 0.0

    for benchmark in ("XBI", "IBB"):
        df = benchmark_frames.get(benchmark)
        if not isinstance(df, pd.DataFrame) or len(df) < 2:
            continue
        sector_ret = _window_return(df)
        relative = sector_ret - spy_ret
        if relative <= -0.08:
            date = _latest_date(df)
            events.append(
                {
                    "id": _event_id(ticker, "sector_underperformance", date, benchmark),
                    "date": date,
                    "type": "sector_underperformance",
                    "category": "macro",
                    "priority": 2,
                    "ticker": ticker,
                    "disease_area": "",
                    "catalyst": f"{benchmark} underperformed SPY by {relative:.1%} over the macro window",
                    "title": f"{benchmark} biotech sector underperformance",
                    "summary": f"{benchmark} relative return versus SPY was {relative:.1%}.",
                    "sentiment": "negative",
                    "price_impact": None,
                    "source": "macro_regime",
                    "source_entity": benchmark,
                    "source_ids": [benchmark],
                    "confidence": "medium",
                    "metadata": {
                        "benchmark": benchmark,
                        "relative_return": round(relative, 6),
                        "backtest_eligible": True,
                    },
                }
            )

    vix = benchmark_frames.get("^VIX")
    if isinstance(vix, pd.DataFrame) and not vix.empty:
        latest_vix = float(vix["close"].iloc[-1])
        if latest_vix >= 30:
            date = _latest_date(vix)
            events.append(
                {
                    "id": _event_id(ticker, "macro_risk_off", date, "^VIX"),
                    "date": date,
                    "type": "macro_risk_off",
                    "category": "macro",
                    "priority": 2,
                    "ticker": ticker,
                    "disease_area": "",
                    "catalyst": f"VIX elevated at {latest_vix:.1f}",
                    "title": "Macro risk-off regime",
                    "summary": f"VIX closed at {latest_vix:.1f}, indicating elevated market stress.",
                    "sentiment": "negative",
                    "price_impact": None,
                    "source": "macro_regime",
                    "source_entity": "^VIX",
                    "source_ids": ["^VIX"],
                    "confidence": "medium",
                    "metadata": {
                        "benchmark": "^VIX",
                        "level": latest_vix,
                        "backtest_eligible": True,
                    },
                }
            )

    return events


def fetch_macro_regime_events(
    ticker: str,
    loader: Callable[[str], pd.DataFrame] = load_ohlc,
) -> list[dict]:
    frames: dict[str, pd.DataFrame] = {}
    for symbol in BENCHMARKS:
        try:
            df = loader(symbol)
        except Exception:
            continue
        if isinstance(df, pd.DataFrame) and not df.empty:
            frames[symbol] = df.tail(30).copy()
    return build_macro_regime_events(ticker, frames)
```

- [ ] **Step 4: Add macro source to ingestion**

In `event_ingestion_service.py`, add `"macro_regime"` to the source list after `"gdelt"`.

Add branch:

```python
elif source == "macro_regime":
    events = fetch_macro_regime_events(ticker)
    events = _enrich_events(
        events,
        ticker=ticker,
        source=source,
        source_run_id=source_run_id,
        query_hash=query_hash,
    )
    item_count = len(events)
    if events:
        insert_events(events)
        logger.info(f"Inserted {item_count} macro regime events for {ticker}")
    record_fetch_attempt(
        ticker,
        source,
        item_count,
        status="ready" if item_count > 0 else "empty",
    )
```

Update ingestion tests that monkeypatch source functions to also monkeypatch `fetch_macro_regime_events`.

- [ ] **Step 5: Run GREEN verification**

Run:

```bash
pytest tests/test_macro_regime_client.py tests/test_event_ingestion_trust_boundary.py tests/test_event_ingestion_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/tools/macro_regime_client.py src/services/event_ingestion_service.py tests/test_macro_regime_client.py tests/test_event_ingestion_trust_boundary.py tests/test_event_ingestion_service.py
git commit -m "feat(kline): add trusted macro regime events"
```

---

## Task 4: Trusted Backtest Inputs and Latest Run Index

**Files:**
- Modify: `src/backtest/runner.py`
- Modify: `src/kline/providers/backtest_provider.py`
- Test: `tests/test_kline_backtest_trusted_inputs.py`
- Extend: `tests/test_kline_backtest_runner.py`

- [ ] **Step 1: Write failing backtest trust/index tests**

Create `tests/test_kline_backtest_trusted_inputs.py`:

```python
import json

import pandas as pd

from src.backtest import runner
from src.kline.providers.backtest_provider import BacktestResultProvider


def price_frame():
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=5, freq="D"),
            "open": [10, 10, 10, 10, 10],
            "high": [11, 11, 11, 11, 11],
            "low": [9, 9, 9, 9, 9],
            "close": [10, 11, 12, 11, 13],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )


def trusted_events():
    return pd.DataFrame(
        [
            {
                "id": "trusted-event",
                "date": "2025-01-02",
                "type": "trial_results_posted",
                "priority": 1,
                "ticker": "MRNA",
                "ticker_scope": "MRNA",
                "sentiment": "positive",
                "source": "clinicaltrials",
                "ownership_status": "owned",
                "trust_status": "trusted",
                "schema_version": 2,
                "metadata": {"backtest_eligible": True},
            }
        ]
    )


def test_backtest_reads_trusted_events_only(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_ohlc", lambda ticker: price_frame())
    called = {}

    def fake_trusted_events(ticker, start_date=None, end_date=None):
        called["args"] = (ticker, start_date, end_date)
        return trusted_events()

    monkeypatch.setattr(runner, "get_trusted_events_for_backtest", fake_trusted_events)

    result = runner.run_kline_backtest("MRNA", "2025-01-01", "2025-01-05")

    assert called["args"] == ("MRNA", "2025-01-01", "2025-01-05")
    assert result["input_event_ids"] == ["trusted-event"]
    assert result["trust_summary"]["trusted_event_count"] == 1
    assert (tmp_path / "index.json").exists()


def test_backtest_provider_loads_latest_indexed_run(tmp_path):
    run_id = "20260429_120000_abcdef12"
    payload = {"run_id": run_id, "ticker": "MRNA", "metrics": {"sharpe": 1.2}}
    (tmp_path / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps({"latest_by_ticker": {"MRNA": {"run_id": run_id}}}),
        encoding="utf-8",
    )

    provider = BacktestResultProvider(results_dir=tmp_path)

    assert provider.load_last_run("MRNA") == payload
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_kline_backtest_trusted_inputs.py -q
```

Expected: FAIL because runner still imports raw `get_events`, payload lacks trust fields/index, and provider does not read latest runs.

- [ ] **Step 3: Update `runner.py` imports and trusted input**

Replace raw event import:

```python
from src.backtest.events_db import get_trusted_events_for_backtest, init_db, get_fetch_log_entries
```

In `run_kline_backtest()`, replace:

```python
events = get_events(ticker, start_date=start_date, end_date=end_date)
eligible_events, event_filter = filter_backtest_events(events)
```

with:

```python
events = get_trusted_events_for_backtest(
    ticker,
    start_date=start_date,
    end_date=end_date,
)
if events.empty:
    return {"error": "no trusted backtest-eligible events in date range"}
eligible_events, event_filter = filter_backtest_events(events)
```

Add helpers:

```python
def _input_event_ids(events: pd.DataFrame) -> list[str]:
    if events.empty or "id" not in events.columns:
        return []
    return [str(value) for value in events["id"].dropna().tolist()]


def _trust_summary(events: pd.DataFrame) -> dict:
    if events.empty:
        return {"trusted_event_count": 0}
    summary = {"trusted_event_count": int(len(events))}
    if "source" in events.columns:
        summary["by_source"] = events["source"].value_counts().to_dict()
    if "ownership_status" in events.columns:
        summary["by_ownership_status"] = events["ownership_status"].value_counts().to_dict()
    return summary


def _save_run_index(ticker: str, run_id: str, payload: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = RESULTS_DIR / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except json.JSONDecodeError:
        index = {}
    latest = dict(index.get("latest_by_ticker") or {})
    latest[ticker] = {
        "run_id": run_id,
        "ticker": ticker,
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    index["latest_by_ticker"] = latest
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
```

Add payload fields:

```python
"input_event_ids": _input_event_ids(eligible_events),
"trust_summary": _trust_summary(eligible_events),
"source_status_at_run": get_fetch_log_entries(ticker),
```

Call `_save_run_index(ticker, run_id, payload)` after writing the run JSON.

- [ ] **Step 4: Implement latest-run provider**

Replace `BacktestResultProvider` with:

```python
"""Backtest result provider for K-line workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.backtest.runner import RESULTS_DIR, RUN_ID_PATTERN


class BacktestResultProvider:
    def __init__(self, results_dir: Path | None = None):
        self.results_dir = Path(results_dir) if results_dir is not None else RESULTS_DIR

    def load_last_run(self, ticker: str) -> dict[str, Any] | None:
        symbol = str(ticker or "").strip().upper()
        index_path = self.results_dir / "index.json"
        if not symbol or not index_path.exists():
            return None
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        run_info = (index.get("latest_by_ticker") or {}).get(symbol)
        if not isinstance(run_info, dict):
            return None
        run_id = str(run_info.get("run_id") or "")
        if not RUN_ID_PATTERN.fullmatch(run_id):
            return None
        run_path = self.results_dir / f"{run_id}.json"
        if not run_path.exists():
            return None
        try:
            payload = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if str(payload.get("ticker") or "").upper() == symbol else None
```

- [ ] **Step 5: Run GREEN verification**

Run:

```bash
pytest tests/test_kline_backtest_trusted_inputs.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/backtest/runner.py src/kline/providers/backtest_provider.py tests/test_kline_backtest_trusted_inputs.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_service.py
git commit -m "feat(kline): persist trusted backtest runs"
```

---

## Task 5: Workspace and UI Trust Metadata

**Files:**
- Modify: `src/kline/models.py`
- Modify: `src/kline/providers/catalyst_provider.py`
- Modify: `static/kline/workspace.js`
- Modify: `src/kline/chart/types.ts`
- Test: `tests/test_kline_workspace_service.py`
- Test: `tests/test_kline_workspace_js.py`
- Test: `tests/test_kline_web_integration.py`

- [ ] **Step 1: Write failing workspace/UI metadata tests**

Extend `tests/test_kline_workspace_service.py` with:

```python
def test_workspace_event_exposes_trust_metadata():
    from src.kline.workspace_service import KlineWorkspaceService
    from src.kline.providers.ohlc_provider import OHLCProvider
    from src.kline.providers.catalyst_provider import CatalystEventProvider
    from src.kline.providers.backtest_provider import BacktestResultProvider

    service = KlineWorkspaceService(
        ohlc_provider=OHLCProvider(fetch_rows=lambda ticker, max_age: {"rows": [], "status": "empty"}),
        catalyst_provider=CatalystEventProvider(
            fetch_events=lambda ticker, max_age: [
                {
                    "id": "trusted",
                    "date": "2025-01-01",
                    "type": "trial_results_posted",
                    "category": "clinical",
                    "priority": 1,
                    "ticker": ticker,
                    "ticker_scope": ticker,
                    "title": "Trusted event",
                    "summary": "Trusted event",
                    "sentiment": "positive",
                    "source": "clinicaltrials",
                    "trust_status": "trusted",
                    "ownership_status": "owned",
                    "source_run_id": "run-1",
                    "query_hash": "hash-1",
                    "schema_version": 2,
                    "metadata": {"backtest_eligible": True},
                }
            ],
            fetch_statuses=lambda ticker: [],
        ),
        backtest_provider=BacktestResultProvider(),
    )

    event = service.build_workspace("MRNA").to_dict()["layers"][1]["points"][0]

    assert event["trust_status"] == "trusted"
    assert event["ownership_status"] == "owned"
    assert event["source_run_id"] == "run-1"
    assert event["query_hash"] == "hash-1"
```

Extend `tests/test_kline_workspace_js.py` with assertions that `workspace.js` contains these detail labels:

```python
def test_workspace_js_renders_trust_fields():
    script = Path("static/kline/workspace.js").read_text(encoding="utf-8")
    assert '"Trust status"' in script
    assert '"Ownership status"' in script
    assert '"Source run"' in script
    assert '"Query hash"' in script
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py -q
```

Expected: FAIL because Kline event models and JS details do not expose all trust fields.

- [ ] **Step 3: Extend Kline event models**

In `src/kline/models.py`, add fields to `KlineEvent`:

```python
trust_status: str | None = None
ownership_status: str | None = None
source_run_id: str | None = None
query_hash: str | None = None
company_identity: str | None = None
schema_version: int | None = None
quarantine_reason: str | None = None
```

- [ ] **Step 4: Map trust fields in `catalyst_provider.py`**

In `_normalize_event()`, pass raw trust fields through:

```python
trust_status=_optional_string(raw.get("trust_status") or metadata.get("trust_status")),
ownership_status=_optional_string(raw.get("ownership_status") or metadata.get("ownership_status")),
source_run_id=_optional_string(raw.get("source_run_id") or metadata.get("source_run_id")),
query_hash=_optional_string(raw.get("query_hash") or metadata.get("query_hash")),
company_identity=_optional_string(raw.get("company_identity") or metadata.get("company_identity")),
schema_version=_int_or_none(raw.get("schema_version") or metadata.get("schema_version")),
quarantine_reason=_optional_string(raw.get("quarantine_reason") or metadata.get("quarantine_reason")),
```

Add helper:

```python
def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 5: Extend TypeScript event contract and details panel**

In `src/kline/chart/types.ts`, add optional fields to `BiotechEvent`:

```typescript
trust_status?: string;
ownership_status?: string;
source_run_id?: string;
query_hash?: string;
company_identity?: string;
schema_version?: number;
quarantine_reason?: string;
```

In `static/kline/workspace.js`, add these details after source metadata:

```javascript
appendDefinition(list, "Trust status", eventMetadataValue(selected, "trust_status"));
appendDefinition(list, "Ownership status", eventMetadataValue(selected, "ownership_status"));
appendDefinition(list, "Source run", eventMetadataValue(selected, "source_run_id"));
appendDefinition(list, "Query hash", eventMetadataValue(selected, "query_hash"));
appendDefinition(list, "Company identity", eventMetadataValue(selected, "company_identity"));
appendDefinition(list, "Schema version", eventMetadataValue(selected, "schema_version"));
```

- [ ] **Step 6: Run GREEN verification and rebuild chart bundle if needed**

Run:

```bash
pytest tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py -q
npm --prefix src/kline run build
```

Expected: PASS and Vite build succeeds. If `static/vendor/pokie-chart.umd.js` changes, stage it with this task.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/kline/models.py src/kline/providers/catalyst_provider.py src/kline/chart/types.ts static/kline/workspace.js static/vendor/pokie-chart.umd.js tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py
git commit -m "feat(kline): expose event trust metadata"
```

---

## Task 6: Final Verification, Local Quarantine Command, and Cleanup

**Files:**
- Modify: `src/services/event_ingestion_service.py`
- Test: `tests/test_event_ingestion_trust_boundary.py`
- Optional docs: append a short command note to `docs/superpowers/specs/2026-04-29-kline-phase2-data-truth-design.md`

- [ ] **Step 1: Add failing test for explicit quarantine helper**

Extend `tests/test_event_ingestion_trust_boundary.py`:

```python
def test_quarantine_legacy_cache_for_ticker(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    events_db.insert_event(
        {
            "id": "legacy-cache",
            "date": "2025-01-01",
            "type": "market_news",
            "priority": 3,
            "ticker": "MRNA",
            "disease_area": "",
            "catalyst": "Old cached news",
            "sentiment": "neutral",
            "source": "alphavantage",
        }
    )

    updated = event_ingestion_service.quarantine_legacy_cache("MRNA")

    assert updated == 1
    assert event_ingestion_service.get_events_for_ticker("MRNA", max_age_hours=999999) == []
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
pytest tests/test_event_ingestion_trust_boundary.py::test_quarantine_legacy_cache_for_ticker -q
```

Expected: FAIL because `quarantine_legacy_cache()` does not exist.

- [ ] **Step 3: Implement quarantine helper**

In `src/services/event_ingestion_service.py`, import `mark_legacy_events_untrusted` from `events_db` and add:

```python
def quarantine_legacy_cache(ticker: str | None = None) -> int:
    """Mark legacy cached event rows as untrusted without deleting raw data."""
    normalized = ticker.strip().upper() if isinstance(ticker, str) and ticker.strip() else None
    return mark_legacy_events_untrusted(normalized)
```

- [ ] **Step 4: Run full targeted verification**

Run:

```bash
pytest tests/test_kline_event_trust_db.py tests/test_event_ingestion_trust_boundary.py tests/test_macro_regime_client.py tests/test_kline_backtest_trusted_inputs.py tests/test_event_ingestion_service.py tests/test_kline_backtest_runner.py tests/test_kline_workspace_service.py tests/test_kline_workspace_js.py tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q
python -m black --check src/kline/event_trust.py src/services/event_ingestion_service.py src/tools/clinical_trials_client.py src/tools/macro_regime_client.py src/backtest/events_db.py src/backtest/runner.py src/kline/providers/backtest_provider.py src/kline/providers/catalyst_provider.py tests/test_kline_event_trust_db.py tests/test_event_ingestion_trust_boundary.py tests/test_macro_regime_client.py tests/test_kline_backtest_trusted_inputs.py
python -m compileall -q src/kline src/tools/macro_regime_client.py src/services/event_ingestion_service.py src/backtest
npm --prefix src/kline run build
git diff --check
```

Expected:

- All pytest tests pass.
- Black check reports unchanged files.
- Compileall exits with code 0.
- Vite build exits with code 0.
- `git diff --check` exits with code 0.

- [ ] **Step 5: Commit Task 6**

```bash
git add src/services/event_ingestion_service.py tests/test_event_ingestion_trust_boundary.py docs/superpowers/specs/2026-04-29-kline-phase2-data-truth-design.md
git commit -m "chore(kline): add legacy cache quarantine helper"
```

---

## Execution Notes for Subagents

- You are not alone in the codebase. Do not revert edits made by other agents or the user.
- Each task owns only the files listed in that task. If a task needs another file, stop and report the dependency.
- Follow TDD: write the failing test, run it, implement, run it green, then commit.
- Use temporary test databases. Do not mutate the developer's real `data/events.db` in tests.
- Do not physically delete cache rows.
- Keep raw audit reads available; change Kline/backtest consumers to trusted reads.
- After each task, provide:
  - Status: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`
  - Commit SHA
  - Files changed
  - Verification commands and outputs
