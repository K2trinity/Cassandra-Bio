# Biotech Data Download Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline executor that downloads `biotech_us_v1` universe, Tiingo daily adjusted OHLCV, SEC fundamentals, and optional FMP enrichment into the local research store with checkpoint/resume and provider rate limits.

**Architecture:** Keep provider HTTP code out of Flask routes. Add small ingestion modules under `src/data_ingestion`, reuse existing normalizers and DuckDB catalog tables, and expose a single CLI script for dry-run and resumable execution. Tests use fake HTTP clients and fixtures only; real API credentials are read from environment variables only.

**Tech Stack:** Python, requests, pandas, DuckDB, Parquet, pytest, existing Cassandra `src/backtest` and `src/data_ingestion` modules.

---

## Current Context

The previous branch already added:

- `src/backtest/research_db.py` with `security_master`, `universe_membership`, `universe_snapshots`, `data_snapshots`, `provider_fetch_log`, and fundamentals tables.
- `src/data_ingestion/rate_limit.py` with `FixedWindowRateLimit`.
- `src/data_ingestion/provider_log.py` with `record_provider_fetch`.
- `src/data_ingestion/tiingo_prices.py` with `normalize_tiingo_eod_prices`.
- `src/data_ingestion/fundamentals.py` with FMP and SEC normalization.
- `src/backtest/price_snapshot.py` with current snapshot write helpers.
- `scripts/build_biotech_universe_snapshot.py` with a private universe catalog writer.

Do not write API keys, tokens, or email addresses to any git-tracked file. Tests must not make live HTTP requests.

## File Structure

- Create `src/data_ingestion/provider_config.py` for environment loading, provider defaults, and redaction.
- Create `src/data_ingestion/http_client.py` for request hashing, response adapters, and safe URL redaction.
- Create `src/data_ingestion/checkpoints.py` for durable DuckDB checkpoint rows.
- Create `src/data_ingestion/manifest.py` for deterministic snapshot manifest generation and JSON writes.
- Create `src/backtest/universe_catalog.py` for public universe snapshot persistence, refactored out of the script.
- Create `src/data_ingestion/nasdaq_trader.py` for public symbol directory parsing and optional download.
- Create `src/data_ingestion/fmp_client.py` for FMP profile and statement calls.
- Create `src/data_ingestion/sec_client.py` for SEC submissions/companyfacts calls.
- Create `src/data_ingestion/tiingo_client.py` for Tiingo daily price calls.
- Create `src/data_ingestion/fundamentals_store.py` for writing normalized fundamentals rows to DuckDB.
- Modify `src/backtest/price_snapshot.py` to support safe incremental Tiingo partition writes.
- Create `src/data_ingestion/download_executor.py` for orchestration.
- Create `scripts/download_biotech_data.py` as the CLI.
- Create tests for every new module.

---

### Task 1: Provider Config And Safe HTTP Utilities

**Files:**
- Create: `src/data_ingestion/provider_config.py`
- Create: `src/data_ingestion/http_client.py`
- Test: `tests/test_provider_config.py`
- Test: `tests/test_provider_http_client.py`

- [ ] **Step 1: Write failing provider config tests**

Create `tests/test_provider_config.py`:

```python
from __future__ import annotations


def test_load_provider_config_reads_env_without_exposing_values(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-secret")
    monkeypatch.setenv("SEC_USER_AGENT", "CassandraBio user@example.com")

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()

    assert config.tiingo_api_key == "tiingo-secret"
    assert config.fmp_api_key == "fmp-secret"
    assert config.sec_user_agent == "CassandraBio user@example.com"
    assert "tiingo-secret" not in repr(config)
    assert "fmp-secret" not in repr(config)
    assert "user@example.com" not in repr(config)


def test_provider_config_reports_missing_required_provider_credentials(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()

    assert config.available("nasdaq") is True
    assert config.available("tiingo") is False
    assert config.available("fmp") is False
    assert config.available("sec") is False
    assert config.missing_reason("tiingo") == "TIINGO_API_KEY is not set"
    assert config.missing_reason("fmp") == "FMP_API_KEY is not set"
    assert config.missing_reason("sec") == "SEC_USER_AGENT is not set"


def test_redact_text_removes_configured_secret_values(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-secret")
    monkeypatch.setenv("SEC_USER_AGENT", "CassandraBio user@example.com")

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()
    redacted = config.redact(
        "token=tiingo-secret apikey=fmp-secret agent=CassandraBio user@example.com"
    )

    assert redacted == "token=<redacted> apikey=<redacted> agent=<redacted>"
```

- [ ] **Step 2: Write failing HTTP utility tests**

Create `tests/test_provider_http_client.py`:

```python
from __future__ import annotations

import pytest


def test_build_request_hash_is_deterministic_and_ignores_secret_params():
    from src.data_ingestion.http_client import build_request_hash

    first = build_request_hash(
        method="GET",
        url="https://api.tiingo.com/tiingo/daily/MRNA/prices",
        params={"token": "secret", "startDate": "2020-01-01", "endDate": "2020-01-31"},
    )
    second = build_request_hash(
        method="get",
        url="https://api.tiingo.com/tiingo/daily/MRNA/prices",
        params={"endDate": "2020-01-31", "startDate": "2020-01-01", "token": "other"},
    )

    assert first == second
    assert first.startswith("req_")


def test_redact_url_removes_token_and_apikey_query_values():
    from src.data_ingestion.http_client import redact_url

    redacted = redact_url(
        "https://example.test/path?token=abc&apikey=def&symbol=MRNA"
    )

    assert "abc" not in redacted
    assert "def" not in redacted
    assert "token=<redacted>" in redacted
    assert "apikey=<redacted>" in redacted
    assert "symbol=MRNA" in redacted


def test_response_helpers_classify_common_http_statuses():
    from src.data_ingestion.http_client import classify_http_status

    assert classify_http_status(200) == "success"
    assert classify_http_status(404) == "not_found"
    assert classify_http_status(429) == "rate_limited"
    assert classify_http_status(500) == "retryable_error"
    assert classify_http_status(401) == "fatal_error"


def test_fake_response_json_raises_clear_error_for_invalid_json():
    from src.data_ingestion.http_client import HttpResponse

    response = HttpResponse(status_code=200, text="not-json", headers={})

    with pytest.raises(ValueError, match="invalid JSON response"):
        response.json()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
New-Item -ItemType Directory -Force .pytest_tmp | Out-Null
pytest tests/test_provider_config.py tests/test_provider_http_client.py -q --basetemp .pytest_tmp\download-task1-fail
```

Expected: FAIL because the new modules do not exist.

- [ ] **Step 4: Implement provider config**

Create `src/data_ingestion/provider_config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping

PROVIDER_ENV_KEYS = {
    "tiingo": "TIINGO_API_KEY",
    "fmp": "FMP_API_KEY",
    "sec": "SEC_USER_AGENT",
}

PROVIDERS_WITHOUT_CREDENTIALS = frozenset({"nasdaq", "nasdaq_trader"})


@dataclass(frozen=True)
class ProviderConfig:
    tiingo_api_key: str | None = None
    fmp_api_key: str | None = None
    sec_user_agent: str | None = None

    def __repr__(self) -> str:
        return (
            "ProviderConfig("
            f"tiingo_api_key={_presence(self.tiingo_api_key)}, "
            f"fmp_api_key={_presence(self.fmp_api_key)}, "
            f"sec_user_agent={_presence(self.sec_user_agent)})"
        )

    def available(self, provider: str) -> bool:
        key = _provider_key(provider)
        if key in PROVIDERS_WITHOUT_CREDENTIALS:
            return True
        if key == "tiingo":
            return bool(self.tiingo_api_key)
        if key == "fmp":
            return bool(self.fmp_api_key)
        if key == "sec":
            return bool(self.sec_user_agent)
        raise ValueError(f"unsupported provider: {provider}")

    def missing_reason(self, provider: str) -> str | None:
        key = _provider_key(provider)
        if self.available(key):
            return None
        env_key = PROVIDER_ENV_KEYS[key]
        return f"{env_key} is not set"

    def redact(self, text: str) -> str:
        result = str(text)
        for value in (self.tiingo_api_key, self.fmp_api_key, self.sec_user_agent):
            if value:
                result = result.replace(value, "<redacted>")
        return result


def load_provider_config(env: Mapping[str, str] | None = None) -> ProviderConfig:
    source = environ if env is None else env
    return ProviderConfig(
        tiingo_api_key=_optional_env(source, "TIINGO_API_KEY"),
        fmp_api_key=_optional_env(source, "FMP_API_KEY"),
        sec_user_agent=_optional_env(source, "SEC_USER_AGENT"),
    )


def _optional_env(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _provider_key(provider: str) -> str:
    key = str(provider).strip().lower().replace("-", "_")
    if key == "nasdaq_trader":
        return "nasdaq"
    return key


def _presence(value: str | None) -> str:
    return "<set>" if value else "<missing>"
```

- [ ] **Step 5: Implement HTTP utilities**

Create `src/data_ingestion/http_client.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

SECRET_QUERY_KEYS = frozenset({"token", "apikey", "api_key", "access_key"})


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON response") from exc


class RequestsHttpClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        response = self._session.get(
            url,
            params=dict(params or {}),
            headers=dict(headers or {}),
            timeout=self.timeout_seconds,
        )
        return HttpResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )


def build_request_hash(
    *,
    method: str,
    url: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    safe_params = {
        str(key): str(value)
        for key, value in dict(params or {}).items()
        if str(key).lower() not in SECRET_QUERY_KEYS
    }
    payload = {
        "method": str(method).upper(),
        "url": _url_without_query(url),
        "params": dict(sorted(safe_params.items())),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"req_{digest}"


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SECRET_QUERY_KEYS:
            query.append((key, "<redacted>"))
        else:
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def classify_http_status(status_code: int) -> str:
    if 200 <= int(status_code) < 300:
        return "success"
    if int(status_code) == 404:
        return "not_found"
    if int(status_code) == 429:
        return "rate_limited"
    if 500 <= int(status_code) < 600:
        return "retryable_error"
    return "fatal_error"


def _url_without_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
```

- [ ] **Step 6: Run tests to verify Task 1 passes**

Run:

```powershell
pytest tests/test_provider_config.py tests/test_provider_http_client.py -q --basetemp .pytest_tmp\download-task1
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add src\data_ingestion\provider_config.py src\data_ingestion\http_client.py tests\test_provider_config.py tests\test_provider_http_client.py
git commit -m "feat: add provider config and safe http utilities"
```

---

### Task 2: Checkpoint And Manifest Storage

**Files:**
- Modify: `src/backtest/research_db.py`
- Create: `src/data_ingestion/checkpoints.py`
- Create: `src/data_ingestion/manifest.py`
- Test: `tests/test_ingestion_checkpoints.py`
- Test: `tests/test_snapshot_manifest.py`

- [ ] **Step 1: Write failing checkpoint tests**

Create `tests/test_ingestion_checkpoints.py`:

```python
from __future__ import annotations


def test_record_checkpoint_upserts_resumable_unit(tmp_path):
    from src.data_ingestion.checkpoints import (
        IngestionCheckpoint,
        get_checkpoint,
        record_checkpoint,
    )

    db_path = tmp_path / "research.duckdb"
    checkpoint = IngestionCheckpoint(
        run_id="run-1",
        data_snapshot_id="snap-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
        period_start="2020-01-01",
        period_end="2020-01-31",
        status="success",
        attempt_count=1,
        last_error=None,
    )

    record_checkpoint(checkpoint, db_path=db_path)
    loaded = get_checkpoint(
        db_path=db_path,
        run_id="run-1",
        provider="tiingo",
        phase="prices",
        ticker="MRNA",
        endpoint="/tiingo/daily/MRNA/prices",
    )

    assert loaded == checkpoint


def test_completed_checkpoint_is_detected_case_insensitively(tmp_path):
    from src.data_ingestion.checkpoints import IngestionCheckpoint, is_completed, record_checkpoint

    db_path = tmp_path / "research.duckdb"
    record_checkpoint(
        IngestionCheckpoint(
            run_id="run-1",
            data_snapshot_id="snap-1",
            provider="sec",
            phase="companyfacts",
            ticker="mrna",
            endpoint="/companyfacts/MRNA",
            period_start=None,
            period_end=None,
            status="success",
            attempt_count=1,
            last_error=None,
        ),
        db_path=db_path,
    )

    assert is_completed(
        db_path=db_path,
        run_id="run-1",
        provider="SEC",
        phase="companyfacts",
        ticker="MRNA",
        endpoint="/companyfacts/MRNA",
    ) is True
```

- [ ] **Step 2: Write failing manifest tests**

Create `tests/test_snapshot_manifest.py`:

```python
from __future__ import annotations

import json


def test_write_snapshot_manifest_is_deterministic_and_redacts_secrets(tmp_path):
    from src.data_ingestion.manifest import build_snapshot_manifest, write_snapshot_manifest

    manifest = build_snapshot_manifest(
        data_snapshot_id="snap-1",
        snapshot_date="2026-05-08",
        universe_id="biotech_us_v1",
        providers=["tiingo", "sec"],
        universe_member_count=2,
        coverage={"prices": {"tickers": 2}},
        fetch_summary={"tiingo": {"success": 2}},
        skipped=[],
        source_hashes={"universe": "abc"},
        metadata={"note": "token=secret"},
        secret_values=["secret"],
    )

    path = write_snapshot_manifest(manifest, output_dir=tmp_path)

    assert path.name == "snap-1-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["data_snapshot_id"] == "snap-1"
    assert payload["survivorship_bias_warning"] is True
    assert payload["universe_bias_status"] == "current_constituents_only"
    assert "secret" not in path.read_text(encoding="utf-8")
    assert "<redacted>" in path.read_text(encoding="utf-8")
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_ingestion_checkpoints.py tests/test_snapshot_manifest.py -q --basetemp .pytest_tmp\download-task2-fail
```

Expected: FAIL because checkpoint and manifest modules/tables do not exist.

- [ ] **Step 4: Add catalog tables**

Append these statements to `CATALOG_SQL` in `src/backtest/research_db.py`:

```python
    """
    CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
        run_id TEXT,
        data_snapshot_id TEXT,
        provider TEXT,
        phase TEXT,
        ticker TEXT,
        endpoint TEXT,
        period_start DATE,
        period_end DATE,
        status TEXT,
        attempt_count INTEGER,
        last_error TEXT,
        updated_at TIMESTAMP,
        PRIMARY KEY (run_id, provider, phase, ticker, endpoint)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_snapshot_manifests (
        data_snapshot_id TEXT PRIMARY KEY,
        manifest_json TEXT,
        manifest_path TEXT,
        created_at TIMESTAMP
    )
    """,
```

- [ ] **Step 5: Implement checkpoints**

Create `src/data_ingestion/checkpoints.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


@dataclass(frozen=True)
class IngestionCheckpoint:
    run_id: str
    data_snapshot_id: str
    provider: str
    phase: str
    ticker: str
    endpoint: str
    period_start: str | None
    period_end: str | None
    status: str
    attempt_count: int
    last_error: str | None


def record_checkpoint(
    checkpoint: IngestionCheckpoint,
    *,
    db_path: str | Path | None = None,
) -> None:
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    import duckdb

    row = _normalized(checkpoint)
    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            DELETE FROM ingestion_checkpoints
            WHERE run_id = ? AND provider = ? AND phase = ? AND ticker = ? AND endpoint = ?
            """,
            [row.run_id, row.provider, row.phase, row.ticker, row.endpoint],
        )
        conn.execute(
            """
            INSERT INTO ingestion_checkpoints (
                run_id, data_snapshot_id, provider, phase, ticker, endpoint,
                period_start, period_end, status, attempt_count, last_error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                row.run_id,
                row.data_snapshot_id,
                row.provider,
                row.phase,
                row.ticker,
                row.endpoint,
                row.period_start,
                row.period_end,
                row.status,
                row.attempt_count,
                row.last_error,
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_checkpoint(
    *,
    db_path: str | Path | None = None,
    run_id: str,
    provider: str,
    phase: str,
    ticker: str,
    endpoint: str,
) -> IngestionCheckpoint | None:
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    import duckdb

    conn = duckdb.connect(str(path))
    try:
        row = conn.execute(
            """
            SELECT run_id, data_snapshot_id, provider, phase, ticker, endpoint,
                   CAST(period_start AS VARCHAR), CAST(period_end AS VARCHAR),
                   status, attempt_count, last_error
            FROM ingestion_checkpoints
            WHERE run_id = ? AND provider = ? AND phase = ? AND ticker = ? AND endpoint = ?
            """,
            [run_id, _key(provider), _key(phase), _ticker(ticker), endpoint],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return IngestionCheckpoint(*row)


def is_completed(**kwargs) -> bool:
    checkpoint = get_checkpoint(**kwargs)
    return checkpoint is not None and checkpoint.status == "success"


def _normalized(checkpoint: IngestionCheckpoint) -> IngestionCheckpoint:
    return IngestionCheckpoint(
        run_id=checkpoint.run_id.strip(),
        data_snapshot_id=checkpoint.data_snapshot_id.strip(),
        provider=_key(checkpoint.provider),
        phase=_key(checkpoint.phase),
        ticker=_ticker(checkpoint.ticker),
        endpoint=checkpoint.endpoint.strip(),
        period_start=checkpoint.period_start,
        period_end=checkpoint.period_end,
        status=_key(checkpoint.status),
        attempt_count=int(checkpoint.attempt_count),
        last_error=checkpoint.last_error,
    )


def _key(value: str) -> str:
    text = str(value).strip().lower()
    if not text:
        raise ValueError("checkpoint fields must be non-empty")
    return text


def _ticker(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("ticker must be non-empty")
    return text
```

- [ ] **Step 6: Implement manifest helpers**

Create `src/data_ingestion/manifest.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.backtest.research_db import RESEARCH_DIR


def build_snapshot_manifest(
    *,
    data_snapshot_id: str,
    snapshot_date: str,
    universe_id: str,
    providers: Sequence[str],
    universe_member_count: int,
    coverage: Mapping[str, Any],
    fetch_summary: Mapping[str, Any],
    skipped: Sequence[Mapping[str, Any]],
    source_hashes: Mapping[str, str],
    metadata: Mapping[str, Any] | None = None,
    secret_values: Sequence[str] = (),
) -> dict[str, Any]:
    payload = {
        "data_snapshot_id": data_snapshot_id,
        "snapshot_date": snapshot_date,
        "universe_id": universe_id,
        "universe_bias_status": "current_constituents_only",
        "survivorship_bias_warning": True,
        "providers": sorted({provider.strip().lower() for provider in providers}),
        "universe_member_count": int(universe_member_count),
        "coverage": dict(coverage),
        "fetch_summary": dict(fetch_summary),
        "skipped": list(skipped),
        "source_hashes": dict(source_hashes),
        "metadata": dict(metadata or {}),
    }
    return json.loads(_redacted_json(payload, secret_values))


def write_snapshot_manifest(
    manifest: Mapping[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> Path:
    root = Path(output_dir) if output_dir is not None else RESEARCH_DIR / "manifests"
    root.mkdir(parents=True, exist_ok=True)
    snapshot_id = str(manifest["data_snapshot_id"]).strip()
    path = root / f"{snapshot_id}-manifest.json"
    content = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(content + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def _redacted_json(value: Mapping[str, Any], secret_values: Sequence[str]) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for secret in secret_values:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text
```

- [ ] **Step 7: Run tests to verify Task 2 passes**

Run:

```powershell
pytest tests/test_ingestion_checkpoints.py tests/test_snapshot_manifest.py -q --basetemp .pytest_tmp\download-task2
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add src\backtest\research_db.py src\data_ingestion\checkpoints.py src\data_ingestion\manifest.py tests\test_ingestion_checkpoints.py tests\test_snapshot_manifest.py
git commit -m "feat: add ingestion checkpoints and manifests"
```

---

### Task 3: Universe Catalog Writer And Nasdaq Trader Source

**Files:**
- Create: `src/backtest/universe_catalog.py`
- Modify: `scripts/build_biotech_universe_snapshot.py`
- Create: `src/data_ingestion/nasdaq_trader.py`
- Test: `tests/test_universe_catalog.py`
- Test: `tests/test_nasdaq_trader_ingestion.py`

- [ ] **Step 1: Write failing universe catalog tests**

Create `tests/test_universe_catalog.py`:

```python
from __future__ import annotations


def test_write_universe_snapshot_persists_snapshot_and_members(tmp_path):
    import duckdb

    from src.backtest.universe_builder import UniverseSourceRow, build_universe_snapshot
    from src.backtest.universe_catalog import write_universe_snapshot

    db_path = tmp_path / "research.duckdb"
    snapshot = build_universe_snapshot(
        [
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="nasdaq_screener",
                industry="Biotechnology",
                cik="1682852",
            )
        ],
        as_of_date="2026-05-08",
    )

    write_universe_snapshot(snapshot, db_path=db_path)

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT universe_id, member_count, survivorship_bias_warning
            FROM universe_snapshots
            """
        ).fetchone()
        member = conn.execute(
            """
            SELECT security_id, ticker, membership_source
            FROM universe_membership
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == ("biotech_us_v1", 1, True)
    assert member == ("BIO:MRNA", "MRNA", "nasdaq_screener")
```

- [ ] **Step 2: Write failing Nasdaq Trader parser tests**

Create `tests/test_nasdaq_trader_ingestion.py`:

```python
from __future__ import annotations


def test_parse_nasdaq_listed_filters_etfs_test_issues_and_keeps_common_like_rows():
    from src.data_ingestion.nasdaq_trader import parse_nasdaq_listed

    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "MRNA|Moderna, Inc. Common Stock|Q|N|N|100|N|N",
            "XBI|SPDR S&P Biotech ETF|G|N|N|100|Y|N",
            "TEST|Test Company Common Stock|Q|Y|N|100|N|N",
            "File Creation Time: 0508202618:03|||||||",
        ]
    )

    rows = parse_nasdaq_listed(text)

    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "MRNA"
    assert row.exchange == "NASDAQ"
    assert row.asset_type == "common_stock"
    assert row.source == "exchange_listings"


def test_parse_otherlisted_maps_exchange_and_skips_non_common_share_classes():
    from src.data_ingestion.nasdaq_trader import parse_otherlisted

    text = "\n".join(
        [
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
            "DNA|Ginkgo Bioworks Holdings Inc Class A Common Stock|N|DNA|N|100|N|DNA",
            "ABC.W|ABC Corp Warrant|A|ABC.W|N|100|N|ABC.W",
            "File Creation Time: 0508202618:03|||||||",
        ]
    )

    rows = parse_otherlisted(text)

    assert [row.ticker for row in rows] == ["DNA"]
    assert rows[0].exchange == "NYSE"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_universe_catalog.py tests/test_nasdaq_trader_ingestion.py -q --basetemp .pytest_tmp\download-task3-fail
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Create public universe catalog writer**

Move the private write logic from `scripts/build_biotech_universe_snapshot.py` into `src/backtest/universe_catalog.py`. Expose one public function with this signature: `write_universe_snapshot(snapshot: UniverseSnapshot, *, db_path: str | Path | None = None) -> None`.

The implementation should keep the same semantics as the script currently has:

- initialize the research database
- delete same-day replacement rows
- close prior active memberships
- bound replaced memberships before the next snapshot date
- insert `universe_snapshots`
- insert `universe_membership`

Update `scripts/build_biotech_universe_snapshot.py` to import and call
`write_universe_snapshot` instead of its private `_write_snapshot` helper.

- [ ] **Step 5: Implement Nasdaq Trader parser**

Create `src/data_ingestion/nasdaq_trader.py` with:

```python
from __future__ import annotations

import csv
from io import StringIO
from typing import Iterable

from src.backtest.universe_builder import UniverseSourceRow

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHERLISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

_OTHER_EXCHANGES = {
    "A": "NYSEAMERICAN",
    "N": "NYSE",
    "P": "NYSEARCA",
    "Z": "BATS",
    "V": "IEX",
}


def parse_nasdaq_listed(text: str) -> list[UniverseSourceRow]:
    rows = []
    for row in _dict_rows(text):
        symbol = row.get("Symbol", "")
        if _skip_row(symbol=symbol, name=row.get("Security Name", ""), etf=row.get("ETF"), test_issue=row.get("Test Issue")):
            continue
        rows.append(
            UniverseSourceRow(
                ticker=symbol.strip().upper(),
                company_name=row["Security Name"].strip(),
                exchange="NASDAQ",
                asset_type="common_stock",
                source="exchange_listings",
            )
        )
    return rows


def parse_otherlisted(text: str) -> list[UniverseSourceRow]:
    rows = []
    for row in _dict_rows(text):
        symbol = row.get("ACT Symbol", "")
        if _skip_row(symbol=symbol, name=row.get("Security Name", ""), etf=row.get("ETF"), test_issue=row.get("Test Issue")):
            continue
        exchange = _OTHER_EXCHANGES.get(row.get("Exchange", "").strip().upper(), row.get("Exchange", "").strip().upper())
        rows.append(
            UniverseSourceRow(
                ticker=symbol.strip().upper(),
                company_name=row["Security Name"].strip(),
                exchange=exchange,
                asset_type="common_stock",
                source="exchange_listings",
            )
        )
    return rows


def parse_symbol_directories(*, nasdaqlisted_text: str, otherlisted_text: str) -> list[UniverseSourceRow]:
    return [*parse_nasdaq_listed(nasdaqlisted_text), *parse_otherlisted(otherlisted_text)]


def _dict_rows(text: str) -> Iterable[dict[str, str]]:
    cleaned_lines = [
        line for line in text.splitlines()
        if line.strip() and not line.startswith("File Creation Time:")
    ]
    yield from csv.DictReader(StringIO("\n".join(cleaned_lines)), delimiter="|")


def _skip_row(*, symbol: str, name: str, etf: str | None, test_issue: str | None) -> bool:
    upper_symbol = symbol.strip().upper()
    upper_name = name.strip().upper()
    if not upper_symbol:
        return True
    if (test_issue or "").strip().upper() == "Y":
        return True
    if (etf or "").strip().upper() == "Y":
        return True
    if any(token in upper_symbol for token in (".W", ".U", ".R", ".P")):
        return True
    if any(word in upper_name for word in (" WARRANT", " RIGHT", " UNIT", " PREFERRED")):
        return True
    return False
```

- [ ] **Step 6: Run tests to verify Task 3 passes**

Run:

```powershell
pytest tests/test_universe_catalog.py tests/test_nasdaq_trader_ingestion.py tests/test_build_biotech_universe_snapshot.py -q --basetemp .pytest_tmp\download-task3
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add src\backtest\universe_catalog.py scripts\build_biotech_universe_snapshot.py src\data_ingestion\nasdaq_trader.py tests\test_universe_catalog.py tests\test_nasdaq_trader_ingestion.py tests\test_build_biotech_universe_snapshot.py
git commit -m "feat: add nasdaq trader universe ingestion"
```

---

### Task 4: Provider Clients For Tiingo, SEC, And FMP

**Files:**
- Create: `src/data_ingestion/tiingo_client.py`
- Create: `src/data_ingestion/sec_client.py`
- Create: `src/data_ingestion/fmp_client.py`
- Test: `tests/test_tiingo_client.py`
- Test: `tests/test_sec_client.py`
- Test: `tests/test_fmp_client.py`

- [ ] **Step 1: Write failing Tiingo client tests**

Create `tests/test_tiingo_client.py`:

```python
from __future__ import annotations


class FakeHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        from src.data_ingestion.http_client import HttpResponse

        self.calls.append((url, params, headers))
        return HttpResponse(status_code=200, text='[{"date":"2026-05-01T00:00:00.000Z"}]', headers={})


def test_tiingo_client_uses_authorization_header_and_safe_request_hash():
    from src.data_ingestion.tiingo_client import TiingoClient

    fake = FakeHttp()
    client = TiingoClient(api_key="secret-token", http_client=fake)

    result = client.fetch_daily_prices(
        ticker="MRNA",
        start_date="2026-05-01",
        end_date="2026-05-08",
    )

    assert result.status == "success"
    assert result.rows == [{"date": "2026-05-01T00:00:00.000Z"}]
    assert result.request_hash.startswith("req_")
    url, params, headers = fake.calls[0]
    assert url.endswith("/tiingo/daily/MRNA/prices")
    assert params == {"startDate": "2026-05-01", "endDate": "2026-05-08", "resampleFreq": "daily"}
    assert headers["Authorization"] == "Token secret-token"
    assert "secret-token" not in result.request_hash
```

- [ ] **Step 2: Write failing SEC and FMP client tests**

Create `tests/test_sec_client.py`:

```python
from __future__ import annotations


class FakeHttp:
    def __init__(self, status_code=200, text='{"facts":{}}'):
        self.status_code = status_code
        self.text = text
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        from src.data_ingestion.http_client import HttpResponse

        self.calls.append((url, params, headers))
        return HttpResponse(status_code=self.status_code, text=self.text, headers={})


def test_sec_client_zero_pads_cik_and_sends_user_agent():
    from src.data_ingestion.sec_client import SecClient

    fake = FakeHttp()
    client = SecClient(user_agent="CassandraBio user@example.com", http_client=fake)

    result = client.fetch_companyfacts(cik="1682852")

    assert result.status == "success"
    assert fake.calls[0][0].endswith("/api/xbrl/companyfacts/CIK0001682852.json")
    assert fake.calls[0][2]["User-Agent"] == "CassandraBio user@example.com"
    assert result.payload == {"facts": {}}
```

Create `tests/test_fmp_client.py`:

```python
from __future__ import annotations


class FakeHttp:
    def __init__(self, text='[{"symbol":"MRNA","industry":"Biotechnology"}]'):
        self.text = text
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        from src.data_ingestion.http_client import HttpResponse

        self.calls.append((url, params, headers))
        return HttpResponse(status_code=200, text=self.text, headers={})


def test_fmp_client_uses_apikey_param_but_request_hash_excludes_secret():
    from src.data_ingestion.fmp_client import FmpClient

    fake = FakeHttp()
    client = FmpClient(api_key="fmp-secret", http_client=fake)

    result = client.fetch_profile("MRNA")

    assert result.status == "success"
    assert result.payload == [{"symbol": "MRNA", "industry": "Biotechnology"}]
    assert fake.calls[0][1] == {"apikey": "fmp-secret"}
    assert "fmp-secret" not in result.request_hash
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_tiingo_client.py tests/test_sec_client.py tests/test_fmp_client.py -q --basetemp .pytest_tmp\download-task4-fail
```

Expected: FAIL because clients do not exist.

- [ ] **Step 4: Implement provider result dataclass in each client or shared locally**

Each client should return a small dataclass with:

```python
@dataclass(frozen=True)
class ProviderResult:
    status: str
    request_hash: str
    payload: Any | None = None
    rows: list[dict[str, Any]] | None = None
    message: str | None = None
    retry_after_seconds: float | None = None
```

The status should come from `classify_http_status`.

- [ ] **Step 5: Implement Tiingo client**

Create `src/data_ingestion/tiingo_client.py` with:

```python
TIINGO_DAILY_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
```

`fetch_daily_prices(ticker, start_date, end_date)` must:

- normalize ticker to uppercase
- send `Authorization: Token <api_key>`
- send params `startDate`, `endDate`, and `resampleFreq=daily`
- build request hash without the secret
- return rows for success
- preserve `Retry-After` for 429

- [ ] **Step 6: Implement SEC client**

Create `src/data_ingestion/sec_client.py` with:

```python
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
```

`fetch_companyfacts(cik)` and `fetch_submissions(cik)` must:

- zero-pad CIK to 10 digits
- send `User-Agent`
- send `Accept-Encoding: gzip, deflate`
- send `Host: data.sec.gov`
- return parsed JSON payload for success

- [ ] **Step 7: Implement FMP client**

Create `src/data_ingestion/fmp_client.py` with:

```python
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
```

Add:

- `fetch_profile(ticker)` calling `/profile/{ticker}`
- `fetch_income_statement(ticker, period="quarter")`
- `fetch_balance_sheet(ticker, period="quarter")`
- `fetch_cash_flow(ticker, period="quarter")`

All calls use `apikey` query param and build request hashes without the key.

- [ ] **Step 8: Run tests to verify Task 4 passes**

Run:

```powershell
pytest tests/test_tiingo_client.py tests/test_sec_client.py tests/test_fmp_client.py -q --basetemp .pytest_tmp\download-task4
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```powershell
git add src\data_ingestion\tiingo_client.py src\data_ingestion\sec_client.py src\data_ingestion\fmp_client.py tests\test_tiingo_client.py tests\test_sec_client.py tests\test_fmp_client.py
git commit -m "feat: add biotech provider clients"
```

---

### Task 5: Incremental Price And Fundamental Writers

**Files:**
- Modify: `src/backtest/price_snapshot.py`
- Create: `src/data_ingestion/fundamentals_store.py`
- Test: `tests/test_price_snapshot_incremental.py`
- Test: `tests/test_fundamentals_store.py`

- [ ] **Step 1: Write failing incremental price tests**

Create `tests/test_price_snapshot_incremental.py`:

```python
from __future__ import annotations


def _tiingo_row(date):
    return {
        "date": date,
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 103.0,
        "volume": 12345,
        "adjOpen": 50.0,
        "adjHigh": 52.5,
        "adjLow": 49.5,
        "adjClose": 51.5,
        "adjVolume": 24690,
        "divCash": 0.0,
        "splitFactor": 2.0,
    }


def test_append_prices_daily_frame_allows_new_ticker_in_existing_snapshot(tmp_path):
    from src.backtest.price_snapshot import append_prices_daily_frame
    from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

    output_root = tmp_path / "prices_daily"
    first = normalize_tiingo_eod_prices(
        [_tiingo_row("2026-05-01T00:00:00.000Z")],
        ticker="MRNA",
        data_snapshot_id="snap-1",
    )
    second = normalize_tiingo_eod_prices(
        [_tiingo_row("2026-05-01T00:00:00.000Z")],
        ticker="DNA",
        data_snapshot_id="snap-1",
    )

    append_prices_daily_frame(first, output_root=output_root)
    append_prices_daily_frame(second, output_root=output_root)

    assert (output_root / "data_snapshot_id=snap-1" / "source=tiingo" / "year=2026" / "MRNA.parquet").exists()
    assert (output_root / "data_snapshot_id=snap-1" / "source=tiingo" / "year=2026" / "DNA.parquet").exists()
```

- [ ] **Step 2: Write failing fundamentals store tests**

Create `tests/test_fundamentals_store.py`:

```python
from __future__ import annotations

import json


def test_write_normalized_fundamentals_replaces_rows_for_source_and_ticker(tmp_path):
    import duckdb

    from src.data_ingestion.fundamentals_store import write_fundamentals_rows

    db_path = tmp_path / "research.duckdb"
    rows = [
        {
            "security_id": "FMP:MRNA",
            "ticker": "MRNA",
            "fiscal_period": "2026-Q1",
            "filing_date": "2026-05-01",
            "source": "fmp",
            "cash_and_equivalents": 100.0,
        }
    ]

    write_fundamentals_rows(rows, source="fmp", ticker="MRNA", db_path=db_path)
    write_fundamentals_rows(rows, source="fmp", ticker="MRNA", db_path=db_path)

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute(
            """
            SELECT security_id, ticker, fiscal_period, CAST(filing_date AS VARCHAR), source, payload_json
            FROM fundamentals_normalized
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(stored) == 1
    assert stored[0][:5] == ("FMP:MRNA", "MRNA", "2026-Q1", "2026-05-01", "fmp")
    assert json.loads(stored[0][5])["cash_and_equivalents"] == 100.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_price_snapshot_incremental.py tests/test_fundamentals_store.py -q --basetemp .pytest_tmp\download-task5-fail
```

Expected: FAIL because incremental writer and fundamentals store do not exist.

- [ ] **Step 4: Add incremental price writer**

Add to `src/backtest/price_snapshot.py`:

```python
def append_prices_daily_frame(
    frame: pd.DataFrame,
    *,
    output_root: str | Path | None = None,
) -> None:
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Price frame missing columns: {missing}")
    _validate_price_frame_partition_keys(frame)

    root = Path(output_root) if output_root is not None else RESEARCH_DIR / "prices_daily"
    pending_writes = []
    for (source, data_snapshot_id), group in frame.groupby(
        ["source", "data_snapshot_id"],
        sort=True,
    ):
        source = _validate_source(source)
        data_snapshot_id = _safe_partition_token("data_snapshot_id", data_snapshot_id)
        pending_writes.extend(
            _plan_partition_writes(
                group[PRICE_COLUMNS],
                root,
                source=source,
                data_snapshot_id=data_snapshot_id,
            )
        )
    _preflight_partition_writes(pending_writes)
    _write_planned_partitions(pending_writes)
```

This differs from `write_prices_daily_frame` by allowing an existing snapshot
root while still rejecting an existing ticker/year parquet file.

- [ ] **Step 5: Add fundamentals store**

Create `src/data_ingestion/fundamentals_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


def write_fundamentals_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    ticker: str,
    db_path: str | Path | None = None,
) -> int:
    normalized_source = source.strip().lower()
    normalized_ticker = ticker.strip().upper()
    payloads = [dict(row) for row in rows]
    path = initialize_research_database(db_path or RESEARCH_DB_PATH)
    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            "DELETE FROM fundamentals_normalized WHERE source = ? AND ticker = ?",
            [normalized_source, normalized_ticker],
        )
        for row in payloads:
            conn.execute(
                """
                INSERT INTO fundamentals_normalized (
                    security_id, ticker, fiscal_period, filing_date, source, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    str(row.get("security_id") or ""),
                    normalized_ticker,
                    str(row.get("fiscal_period") or ""),
                    row.get("filing_date") or row.get("filed"),
                    normalized_source,
                    json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False),
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(payloads)
```

- [ ] **Step 6: Run tests to verify Task 5 passes**

Run:

```powershell
pytest tests/test_price_snapshot_incremental.py tests/test_fundamentals_store.py tests/test_tiingo_price_ingestion.py -q --basetemp .pytest_tmp\download-task5
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```powershell
git add src\backtest\price_snapshot.py src\data_ingestion\fundamentals_store.py tests\test_price_snapshot_incremental.py tests\test_fundamentals_store.py tests\test_tiingo_price_ingestion.py
git commit -m "feat: add incremental data writers"
```

---

### Task 6: Download Executor Orchestrator

**Files:**
- Create: `src/data_ingestion/download_executor.py`
- Test: `tests/test_biotech_download_executor.py`

- [ ] **Step 1: Write failing executor tests**

Create `tests/test_biotech_download_executor.py`:

```python
from __future__ import annotations


class FakeTiingoClient:
    def fetch_daily_prices(self, *, ticker, start_date, end_date):
        from src.data_ingestion.tiingo_client import ProviderResult

        return ProviderResult(
            status="success",
            request_hash=f"req_{ticker}",
            rows=[
                {
                    "date": "2026-05-01T00:00:00.000Z",
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 103.0,
                    "volume": 12345,
                    "adjOpen": 50.0,
                    "adjHigh": 52.5,
                    "adjLow": 49.5,
                    "adjClose": 51.5,
                    "adjVolume": 24690,
                    "divCash": 0.0,
                    "splitFactor": 2.0,
                }
            ],
        )


def test_dry_run_plans_units_without_fetching(tmp_path):
    from src.backtest.universe_builder import UniverseSourceRow
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo", "sec"),
        dry_run=True,
        limit_tickers=1,
        research_dir=tmp_path,
    )

    summary = run_download(
        request,
        universe_rows=[
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="exchange_listings",
                industry="Biotechnology",
                cik="1682852",
            )
        ],
    )

    assert summary.dry_run is True
    assert summary.planned_units >= 2
    assert summary.completed_units == 0
    assert summary.universe_member_count == 1


def test_executor_downloads_tiingo_prices_and_checkpoints_success(tmp_path):
    from src.backtest.universe_builder import UniverseSourceRow
    from src.data_ingestion.download_executor import DownloadRequest, run_download

    request = DownloadRequest(
        snapshot_date="2026-05-08",
        start_date="2026-05-01",
        end_date="2026-05-08",
        providers=("tiingo",),
        dry_run=False,
        limit_tickers=1,
        research_dir=tmp_path,
    )

    summary = run_download(
        request,
        universe_rows=[
            UniverseSourceRow(
                ticker="MRNA",
                company_name="Moderna, Inc.",
                exchange="NASDAQ",
                asset_type="common_stock",
                source="exchange_listings",
                industry="Biotechnology",
                cik="1682852",
            )
        ],
        tiingo_client=FakeTiingoClient(),
    )

    assert summary.completed_units == 1
    assert (tmp_path / "prices_daily").rglob("*.parquet")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_biotech_download_executor.py -q --basetemp .pytest_tmp\download-task6-fail
```

Expected: FAIL because the executor does not exist.

- [ ] **Step 3: Implement executor dataclasses**

Create `src/data_ingestion/download_executor.py` with:

```python
@dataclass(frozen=True)
class DownloadRequest:
    snapshot_date: str
    start_date: str
    end_date: str
    providers: tuple[str, ...]
    dry_run: bool = True
    resume: bool = True
    limit_tickers: int | None = None
    universe_id: str = BIOTECH_US_UNIVERSE_ID
    research_dir: str | Path = RESEARCH_DIR
    daily_fmp_budget: int = 240


@dataclass(frozen=True)
class DownloadSummary:
    data_snapshot_id: str
    dry_run: bool
    providers: tuple[str, ...]
    universe_member_count: int
    planned_units: int
    completed_units: int
    skipped_units: int
    failed_units: int
    rate_limited_units: int
    manifest_path: str | None
```

- [ ] **Step 4: Implement orchestration**

`run_download()` must:

- initialize research database in `request.research_dir / "cassandra_research.duckdb"`
- build a universe snapshot from injected `universe_rows`
- persist the universe snapshot with `write_universe_snapshot` unless dry-run
- generate deterministic `data_snapshot_id` with existing snapshot builder
- plan units for selected providers and limited tickers
- for dry-run, write no provider data and return planned counts
- for Tiingo execute per ticker:
  - skip completed checkpoints when `resume=True`
  - call injected `tiingo_client` or construct a real client from config
  - record provider fetch log
  - normalize rows with `normalize_tiingo_eod_prices`
  - append price partitions with `append_prices_daily_frame`
  - record checkpoint
- write a manifest at the end for non-dry-run and dry-run

Keep SEC/FMP execution stubs in this task if needed, but they must plan units
and record skipped units when no client or credential is available. Task 7 will
wire the CLI and broader provider execution.

- [ ] **Step 5: Run tests to verify Task 6 passes**

Run:

```powershell
pytest tests/test_biotech_download_executor.py tests/test_ingestion_checkpoints.py tests/test_provider_fetch_log.py -q --basetemp .pytest_tmp\download-task6
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```powershell
git add src\data_ingestion\download_executor.py tests\test_biotech_download_executor.py
git commit -m "feat: add biotech download executor"
```

---

### Task 7: CLI Entrypoint And Provider Guardrails

**Files:**
- Create: `scripts/download_biotech_data.py`
- Test: `tests/test_download_biotech_data_cli.py`
- Modify: `src/data_ingestion/download_executor.py`
- Test: `tests/test_biotech_download_executor.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_download_biotech_data_cli.py`:

```python
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_download_biotech_data_help_does_not_require_credentials():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/download_biotech_data.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--snapshot-date" in result.stdout
    assert "--providers" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--limit-tickers" in result.stdout


def test_download_biotech_data_dry_run_uses_fixture_universe(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "exchange_listings.csv"
    fixture.write_text(
        "ticker,company_name,exchange,asset_type,industry,cik\n"
        "MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/download_biotech_data.py",
            "--snapshot-date",
            "2026-05-08",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-08",
            "--providers",
            "tiingo,sec",
            "--dry-run",
            "--limit-tickers",
            "1",
            "--exchange-listings-csv",
            str(fixture),
            "--research-dir",
            str(tmp_path / "research"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"dry_run": true' in result.stdout
    assert "TIINGO_API_KEY" not in result.stdout
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```powershell
pytest tests/test_download_biotech_data_cli.py -q --basetemp .pytest_tmp\download-task7-fail
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement CLI**

Create `scripts/download_biotech_data.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.backtest.research_db import RESEARCH_DIR
from src.backtest.universe_builder import UniverseSourceRow
from src.data_ingestion.download_executor import DownloadRequest, run_download


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--universe-id", default="biotech_us_v1")
    parser.add_argument("--providers", default="nasdaq,sec,tiingo,fmp")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit-tickers", type=int)
    parser.add_argument("--daily-fmp-budget", type=int, default=240)
    parser.add_argument("--research-dir", default=str(RESEARCH_DIR))
    parser.add_argument("--exchange-listings-csv")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    rows = _read_exchange_listing_fixture(args.exchange_listings_csv)
    request = DownloadRequest(
        snapshot_date=args.snapshot_date,
        start_date=args.start_date,
        end_date=args.end_date,
        providers=tuple(provider.strip().lower() for provider in args.providers.split(",") if provider.strip()),
        dry_run=args.dry_run,
        resume=args.resume,
        limit_tickers=args.limit_tickers,
        universe_id=args.universe_id,
        research_dir=args.research_dir,
        daily_fmp_budget=args.daily_fmp_budget,
    )
    summary = run_download(request, universe_rows=rows)
    print(json.dumps(summary.__dict__, sort_keys=True, indent=2))
    return 0


def _read_exchange_listing_fixture(path: str | None) -> list[UniverseSourceRow] | None:
    if not path:
        return None
    with Path(path).open(newline="", encoding="utf-8") as file:
        return [
            UniverseSourceRow(
                ticker=row["ticker"],
                company_name=row["company_name"],
                exchange=row["exchange"],
                asset_type=row["asset_type"],
                source="exchange_listings",
                industry=row.get("industry") or None,
                cik=row.get("cik") or None,
            )
            for row in csv.DictReader(file)
        ]


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add credential guardrails to executor**

Update `run_download()` so real provider construction:

- uses `load_provider_config`
- treats missing Tiingo key as skipped Tiingo units unless Tiingo is the only requested provider, then fails clearly
- treats missing FMP key as skipped FMP units
- treats missing SEC User-Agent as skipped SEC units unless SEC is the only requested provider
- always keeps dry-run credential-free

- [ ] **Step 5: Run tests to verify Task 7 passes**

Run:

```powershell
pytest tests/test_download_biotech_data_cli.py tests/test_biotech_download_executor.py tests/test_provider_config.py -q --basetemp .pytest_tmp\download-task7
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```powershell
git add scripts\download_biotech_data.py src\data_ingestion\download_executor.py tests\test_download_biotech_data_cli.py tests\test_biotech_download_executor.py
git commit -m "feat: add biotech download cli"
```

---

### Task 8: Integration Verification And Documentation Guardrails

**Files:**
- Modify: `docs/superpowers/specs/2026-05-08-biotech-data-download-executor-design.md` only if command examples need correction.
- Test: existing and new tests from Tasks 1-7.

- [ ] **Step 1: Run focused integration suite**

Run:

```powershell
New-Item -ItemType Directory -Force .pytest_tmp | Out-Null
pytest `
  tests/test_provider_config.py `
  tests/test_provider_http_client.py `
  tests/test_ingestion_checkpoints.py `
  tests/test_snapshot_manifest.py `
  tests/test_universe_catalog.py `
  tests/test_nasdaq_trader_ingestion.py `
  tests/test_tiingo_client.py `
  tests/test_sec_client.py `
  tests/test_fmp_client.py `
  tests/test_price_snapshot_incremental.py `
  tests/test_fundamentals_store.py `
  tests/test_biotech_download_executor.py `
  tests/test_download_biotech_data_cli.py `
  tests/test_provider_rate_limit.py `
  tests/test_provider_fetch_log.py `
  tests/test_tiingo_price_ingestion.py `
  tests/test_fundamentals_ingestion.py `
  tests/test_build_biotech_universe_snapshot.py `
  -q --basetemp .pytest_tmp\download-integration
```

Expected: PASS.

- [ ] **Step 2: Run dry-run CLI smoke with fixture**

Create a temporary fixture outside git, then run:

```powershell
$tmp = New-Item -ItemType Directory -Force .pytest_tmp\download-smoke
$fixture = Join-Path $tmp.FullName "exchange_listings.csv"
@"
ticker,company_name,exchange,asset_type,industry,cik
MRNA,Moderna Inc,NASDAQ,common_stock,Biotechnology,1682852
"@ | Set-Content -Path $fixture -Encoding UTF8
python scripts/download_biotech_data.py --snapshot-date 2026-05-08 --start-date 2026-05-01 --end-date 2026-05-08 --providers tiingo,sec --dry-run --limit-tickers 1 --exchange-listings-csv $fixture --research-dir .pytest_tmp\download-smoke\research
```

Expected: command exits 0, prints JSON summary with `"dry_run": true`, and does
not print secrets.

- [ ] **Step 3: Run secret leakage scan**

Run:

```powershell
rg -n "4f701056|FMPyp|k2trinity73|TIINGO_API_KEY=|FMP_API_KEY=|SEC_USER_AGENT=" docs src scripts tests
```

Expected: no matches.

- [ ] **Step 4: Run git diff check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit any documentation/test-command corrections**

If Task 8 required documentation corrections:

```powershell
git add docs\superpowers\specs\2026-05-08-biotech-data-download-executor-design.md
git commit -m "docs: align biotech download executor commands"
```

If no corrections were required, do not create an empty commit.

---

## Final Review Checklist

- [ ] No git-tracked file contains the real Tiingo token, FMP key, or user email.
- [ ] Nasdaq Trader path works without credentials.
- [ ] Dry-run path works without credentials and without live HTTP.
- [ ] Tiingo client keeps token out of request hashes and logs.
- [ ] SEC client sends User-Agent when executing.
- [ ] FMP client tracks request hash without API key.
- [ ] Checkpoints make completed ticker/provider units resumable.
- [ ] Price writes can append new tickers into an existing snapshot without overwriting existing ticker/year parquet files.
- [ ] Fundamentals writes replace source/ticker rows deterministically.
- [ ] Snapshot manifest includes `current_constituents_only` and `survivorship_bias_warning: true`.
- [ ] Flask/K-line routes still do not perform provider downloads.
