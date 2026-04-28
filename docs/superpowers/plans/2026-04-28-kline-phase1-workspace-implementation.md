# Kline Phase 1 Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Kline as a focused Phase 1 biotech catalyst workspace: ticker selection, company/price identity, catalyst particles, details/status/backtest panels, correct ticker attribution, and clear extension contracts for Phase 2 and Phase 3.

**Architecture:** Move Kline into a self-contained Flask blueprint under `src/kline/`. Routes depend on one workspace service, the workspace service depends on injected providers, and the UI consumes one serialized workspace payload. `app.py` registers the blueprint and no longer owns Kline routes or Kline business logic.

**Tech Stack:** Flask, Jinja2, plain browser JavaScript, React/D3 UMD chart bundle, SQLite, pandas, yfinance, pytest, TypeScript, Vite

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/kline/__init__.py` | Package boundary and public exports |
| `src/kline/models.py` | Dataclass contracts for workspace payload, events, layers, status, company, price, and range context |
| `src/kline/ticker_resolver.py` | Ticker normalization, invalid ticker rejection, and small biotech universe metadata |
| `src/kline/workspace_service.py` | Orchestrates resolver, OHLC provider, catalyst provider, backtest provider, capabilities, and range context |
| `src/kline/routes.py` | Kline blueprint, public Kline URLs, Kline JSON APIs, and moved backtest APIs |
| `src/kline/providers/__init__.py` | Provider package exports |
| `src/kline/providers/ohlc_provider.py` | Wraps `get_ohlc_rows` and returns `KlinePriceSeries` plus source status |
| `src/kline/providers/catalyst_provider.py` | Wraps event ingestion, converts raw rows to `KlineEvent`, and preserves requested ticker ownership |
| `src/kline/providers/backtest_provider.py` | Thin read adapter for saved backtest metadata |
| `templates/kline_workspace.html` | New Kline page shell with no inline business logic |
| `static/kline/workspace.css` | Kline-only layout and visual styling |
| `static/kline/workspace.js` | Kline-only browser state, ticker selector, chart rendering, tabs, range context, and backtest calls |
| `tests/test_kline_workspace_service.py` | Unit tests for resolver, providers, workspace payload, range context, and capability contracts |

### Modified Files

| File | Change |
|------|--------|
| `app.py` | Remove Kline imports and route functions; register `kline_bp` after Flask initialization |
| `templates/base.html` | Change Kline navigation endpoint to `url_for('kline.kline_default')` |
| `tests/test_kline_web_integration.py` | Replace legacy inline-template assertions with blueprint, workspace, API, and cleanup assertions |
| `tests/test_event_ingestion_service.py` | Add attribution tests for requested ticker, source entity, source IDs, and metadata |
| `src/backtest/events_db.py` | Add non-destructive schema columns and JSON serialization for event metadata |
| `src/services/event_ingestion_service.py` | Pass requested ticker into source normalizers and keep fetch status behavior |
| `src/tools/clinical_trials_client.py` | Accept `requested_ticker`; store sponsor as `source_entity` and NCT ID as `source_ids` |
| `src/tools/openfda_client.py` | Accept `requested_ticker`; store brand/sponsor/application identifiers as metadata |
| `src/kline/chart/types.ts` | Align event and layer types with the Phase 1 workspace contract |
| `src/kline/chart/CandlestickChart.tsx` | Use category and confidence-aware marker style while preserving existing overlays |

### Deleted Files

Delete these only after the new workspace route and tests pass:

| File | Reason |
|------|--------|
| `templates/kline.html` | Old report-triggering Kline page surface |
| `templates/kline_report.html` | Old 1300-line inline workspace replaced by `kline_workspace.html` and static assets |
| `templates/partials/kline_chart_assets.html` | Old chart partial no longer referenced |
| `templates/partials/kline_chart_runtime.html` | Old chart partial no longer referenced |
| `static/vendor/pokie-chart-loader.js` | Old helper replaced by direct `window.PokieChart.render` call in `static/kline/workspace.js` |

### Unchanged Boundaries

The implementation must not refactor report, graph, PDF, Socket.IO, or config systems except for import cleanup caused by moving Kline routes. Existing dirty files unrelated to Kline must be left intact.

## Implementation Tasks

### Task 1: Lock Phase 1 Contracts With Tests

**Files:**
- Create: `tests/test_kline_workspace_service.py`
- Modify: `tests/test_kline_web_integration.py`
- Modify: `tests/test_event_ingestion_service.py`

- [ ] Add `tests/test_kline_workspace_service.py` with these contract tests:

```python
from src.kline.models import KlineDataStatus, KlineEvent, KlinePriceSeries
from src.kline.providers.catalyst_provider import CatalystEventProvider
from src.kline.ticker_resolver import TickerResolver
from src.kline.workspace_service import KlineWorkspaceService


class FakeOHLCProvider:
    def load(self, ticker: str):
        return (
            KlinePriceSeries(
                rows=[
                    {
                        "date": "2026-04-20",
                        "open": 101.0,
                        "high": 104.0,
                        "low": 100.0,
                        "close": 103.0,
                        "volume": 1200000,
                    }
                ],
                date_range={"start": "2026-04-20", "end": "2026-04-20"},
                last_close=103.0,
                cache_status="ready",
                last_updated=None,
            ),
            [KlineDataStatus(source="ohlc", status="ready", item_count=1)],
        )


class FakeCatalystProvider:
    def load(self, ticker: str):
        return (
            [
                KlineEvent(
                    id="evt-1",
                    ticker=ticker,
                    date="2026-04-20",
                    type="clinical_readout",
                    category="clinical",
                    title="Phase 3 readout",
                    summary="Phase 3 readout",
                    sentiment="positive",
                    priority=1,
                    confidence="high",
                    source="clinicaltrials",
                    source_url="https://clinicaltrials.gov/study/NCT00000001",
                    source_ids=["NCT00000001"],
                    source_entity="ModernaTX, Inc.",
                    disease_area="Melanoma",
                    drug_name=None,
                    impact_score=None,
                    metadata={},
                )
            ],
            [KlineDataStatus(source="clinicaltrials", status="ready", item_count=1)],
        )


class FakeBacktestProvider:
    def load_last_run(self, ticker: str):
        return None


def test_ticker_resolver_normalizes_known_symbol():
    resolver = TickerResolver()

    company = resolver.resolve(" mrna ")

    assert company.ticker == "MRNA"
    assert company.name == "Moderna, Inc."
    assert company.is_biotech is True


def test_ticker_resolver_rejects_path_like_symbols():
    resolver = TickerResolver()

    assert resolver.normalize("../MRNA") is None


def test_catalyst_provider_preserves_requested_ticker():
    provider = CatalystEventProvider(
        fetch_events=lambda ticker, max_age_hours=6: [
            {
                "id": "raw-1",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": "ModernaTX,",
                "disease_area": "Melanoma",
                "catalyst": "Phase 3 readout",
                "sentiment": "positive",
                "source": "clinicaltrials",
                "source_entity": "ModernaTX, Inc.",
                "source_ids": ["NCT00000001"],
            }
        ]
    )

    events, statuses = provider.load("MRNA")

    assert events[0].ticker == "MRNA"
    assert events[0].source_entity == "ModernaTX, Inc."
    assert events[0].source_ids == ["NCT00000001"]
    assert statuses[0].source == "clinicaltrials"
    assert statuses[0].status == "ready"


def test_workspace_payload_contains_phase1_layers_and_disabled_future_capabilities():
    service = KlineWorkspaceService(
        resolver=TickerResolver(),
        ohlc_provider=FakeOHLCProvider(),
        catalyst_provider=FakeCatalystProvider(),
        backtest_provider=FakeBacktestProvider(),
    )

    payload = service.build_workspace("MRNA").to_dict()

    assert payload["ticker"] == "MRNA"
    assert payload["company"]["name"] == "Moderna, Inc."
    assert [layer["kind"] for layer in payload["layers"]] == ["candles", "catalysts", "backtest"]
    assert payload["layers"][1]["points"][0]["ticker"] == "MRNA"
    assert {"id": "news", "enabled": False, "phase": 2} in payload["capabilities"]
    assert {"id": "range_analysis", "enabled": False, "phase": 3} in payload["capabilities"]


def test_range_context_returns_phase1_price_and_catalyst_summary():
    service = KlineWorkspaceService(
        resolver=TickerResolver(),
        ohlc_provider=FakeOHLCProvider(),
        catalyst_provider=FakeCatalystProvider(),
        backtest_provider=FakeBacktestProvider(),
    )

    context = service.build_range_context("MRNA", "2026-04-20", "2026-04-20").to_dict()

    assert context["ticker"] == "MRNA"
    assert context["start_date"] == "2026-04-20"
    assert context["end_date"] == "2026-04-20"
    assert context["catalyst_count"] == 1
    assert context["phase3_ready"] is True
```

- [ ] Replace old inline-template assertions in `tests/test_kline_web_integration.py` with route and workspace assertions. Keep root and investigation tests. The Kline tests must assert:

```python
def test_kline_page_renders_phase1_workspace(monkeypatch):
    from src.kline.models import KlineWorkspacePayload
    import src.kline.routes as routes

    class FakeWorkspaceService:
        def build_workspace(self, symbol: str):
            return KlineWorkspacePayload.example(symbol)

    monkeypatch.setattr(routes, "workspace_service", FakeWorkspaceService())

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="kline-workspace"' in html
    assert 'data-role="ticker-selector"' in html
    assert 'data-panel="catalysts"' in html
    assert 'data-panel="details"' in html
    assert 'data-panel="backtest"' in html
    assert 'data-panel="status"' in html
    assert "/static/vendor/pokie-chart.umd.js" in html
    assert "/static/kline/workspace.js" in html
    assert "/api/analyze" not in html
    assert "request_report" not in html


def test_kline_workspace_api_returns_payload(monkeypatch):
    import src.kline.routes as routes

    class FakeWorkspaceService:
        def build_workspace(self, symbol: str):
            return routes.KlineWorkspacePayload.example(symbol)

    monkeypatch.setattr(routes, "workspace_service", FakeWorkspaceService())

    response = app.test_client().get("/api/kline/workspace/MRNA")

    assert response.status_code == 200
    assert response.get_json()["ticker"] == "MRNA"


def test_kline_navigation_uses_blueprint_endpoint():
    response = app.test_client().get("/investigation")
    html = response.get_data(as_text=True)

    assert 'href="/kline"' in html


def test_kline_cleanup_references_are_absent():
    import pathlib

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in pathlib.Path("templates").glob("**/*.html")
    )

    assert "kline_report.html" not in text
    assert "kline_chart_runtime.html" not in text
    assert "kline_chart_assets.html" not in text
```

- [ ] Add event attribution tests to `tests/test_event_ingestion_service.py`:

```python
def test_clinical_trials_normalizer_preserves_requested_ticker():
    from src.tools.clinical_trials_client import normalize_biotech_events

    events = normalize_biotech_events(
        [
            {
                "nct_id": "NCT00000001",
                "title": "Phase 3 melanoma study",
                "status": "COMPLETED",
                "results_first_posted": "2026-04-20",
                "sponsor": "ModernaTX, Inc.",
                "conditions": "Melanoma",
                "phase": "PHASE3",
                "url": "https://clinicaltrials.gov/study/NCT00000001",
            }
        ],
        source="clinicaltrials",
        requested_ticker="MRNA",
    )

    assert events[0]["ticker"] == "MRNA"
    assert events[0]["source_entity"] == "ModernaTX, Inc."
    assert events[0]["source_ids"] == ["NCT00000001"]


def test_openfda_normalizer_preserves_requested_ticker():
    from src.tools.openfda_client import normalize_biotech_events

    events = normalize_biotech_events(
        {
            "results": [
                {
                    "application_number": "BLA001",
                    "sponsor_name": "ModernaTX, Inc.",
                    "openfda": {"brand_name": ["SPIKEVAX"]},
                    "products": [{"brand_name": "SPIKEVAX"}],
                    "action_type": "APPROVAL",
                    "approval_date": "20260420",
                }
            ]
        },
        source="openfda",
        requested_ticker="MRNA",
    )

    assert events[0]["ticker"] == "MRNA"
    assert events[0]["source_entity"] == "ModernaTX, Inc."
    assert events[0]["source_ids"] == ["BLA001"]
    assert events[0]["metadata"]["brand_names"] == ["SPIKEVAX"]
```

- [ ] Run the new and modified tests before implementation:

```powershell
pytest tests/test_kline_workspace_service.py tests/test_kline_web_integration.py tests/test_event_ingestion_service.py -q
```

Expected result: failures for missing `src.kline` modules and old Kline assertions. This confirms the red baseline.

- [ ] Commit after the red tests are written:

```powershell
git add tests/test_kline_workspace_service.py tests/test_kline_web_integration.py tests/test_event_ingestion_service.py
git commit -m "test: lock kline phase1 workspace contracts"
```

Expected output contains `test: lock kline phase1 workspace contracts`.

### Task 2: Add Kline Models, Resolver, Providers, and Workspace Service

**Files:**
- Create: `src/kline/__init__.py`
- Create: `src/kline/models.py`
- Create: `src/kline/ticker_resolver.py`
- Create: `src/kline/workspace_service.py`
- Create: `src/kline/providers/__init__.py`
- Create: `src/kline/providers/ohlc_provider.py`
- Create: `src/kline/providers/catalyst_provider.py`
- Create: `src/kline/providers/backtest_provider.py`

- [ ] Create `src/kline/models.py` with concrete dataclass contracts:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


LayerKind = Literal["candles", "catalysts", "backtest", "news", "macro", "forecast", "range_analysis"]
LayerStatus = Literal["ready", "empty", "loading", "error", "disabled"]
DataStatus = Literal["ready", "empty", "stale", "rate_limited", "error", "disabled"]
EventCategory = Literal["clinical", "regulatory", "corporate", "macro", "report"]
Sentiment = Literal["positive", "negative", "neutral", "unknown"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class KlineCompany:
    ticker: str
    name: str
    aliases: list[str] = field(default_factory=list)
    sector: str = "Healthcare"
    is_biotech: bool = False


@dataclass(frozen=True)
class KlinePriceSeries:
    rows: list[dict[str, Any]]
    date_range: dict[str, str | None]
    last_close: float | None
    cache_status: str
    last_updated: str | None = None


@dataclass(frozen=True)
class KlineDataStatus:
    source: str
    status: DataStatus
    item_count: int
    last_fetch_at: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class KlineWarning:
    code: str
    message: str
    source: str | None = None


@dataclass(frozen=True)
class KlineCapability:
    id: str
    enabled: bool
    phase: int
    label: str


@dataclass(frozen=True)
class KlineEvent:
    id: str
    ticker: str
    date: str
    type: str
    category: EventCategory
    title: str
    summary: str
    sentiment: Sentiment
    priority: int
    confidence: Confidence
    source: str
    source_url: str | None = None
    source_ids: list[str] = field(default_factory=list)
    source_entity: str | None = None
    disease_area: str | None = None
    drug_name: str | None = None
    impact_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KlineLayer:
    id: str
    kind: LayerKind
    label: str
    visible_by_default: bool
    status: LayerStatus
    points: list[KlineEvent] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class KlinePanelState:
    active_panel: str = "catalysts"
    selected_event_id: str | None = None
    last_backtest_run_id: str | None = None


@dataclass(frozen=True)
class KlineWorkspacePayload:
    ticker: str
    company: KlineCompany
    price: KlinePriceSeries
    layers: list[KlineLayer]
    panels: KlinePanelState
    data_status: list[KlineDataStatus]
    warnings: list[KlineWarning]
    capabilities: list[KlineCapability]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def example(cls, symbol: str) -> "KlineWorkspacePayload":
        ticker = symbol.strip().upper() or "MRNA"
        event = KlineEvent(
            id="evt-example",
            ticker=ticker,
            date="2026-04-20",
            type="clinical_readout",
            category="clinical",
            title="Phase 3 readout",
            summary="Phase 3 readout",
            sentiment="positive",
            priority=1,
            confidence="high",
            source="clinicaltrials",
            source_entity="ModernaTX, Inc.",
            source_ids=["NCT00000001"],
        )
        return cls(
            ticker=ticker,
            company=KlineCompany(ticker=ticker, name="Moderna, Inc.", aliases=["Moderna"], is_biotech=True),
            price=KlinePriceSeries(
                rows=[{"date": "2026-04-20", "open": 101.0, "high": 104.0, "low": 100.0, "close": 103.0, "volume": 1200000}],
                date_range={"start": "2026-04-20", "end": "2026-04-20"},
                last_close=103.0,
                cache_status="ready",
            ),
            layers=[
                KlineLayer(id="candles", kind="candles", label="Candles", visible_by_default=True, status="ready"),
                KlineLayer(id="catalysts", kind="catalysts", label="Catalysts", visible_by_default=True, status="ready", points=[event]),
                KlineLayer(id="backtest", kind="backtest", label="Backtest", visible_by_default=False, status="empty"),
            ],
            panels=KlinePanelState(),
            data_status=[
                KlineDataStatus(source="ohlc", status="ready", item_count=1),
                KlineDataStatus(source="clinicaltrials", status="ready", item_count=1),
            ],
            warnings=[],
            capabilities=[
                KlineCapability(id="news", enabled=False, phase=2, label="News"),
                KlineCapability(id="macro", enabled=False, phase=2, label="Macro"),
                KlineCapability(id="forecast", enabled=False, phase=3, label="Forecast"),
                KlineCapability(id="range_analysis", enabled=False, phase=3, label="Range Analysis"),
            ],
        )


@dataclass(frozen=True)
class KlineRangeContext:
    ticker: str
    start_date: str
    end_date: str
    price_change_pct: float | None
    catalyst_count: int
    catalysts: list[KlineEvent]
    phase3_ready: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] Create `src/kline/ticker_resolver.py`:

```python
import re

from src.kline.models import KlineCompany


_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")

_BIOTECH_UNIVERSE: dict[str, dict[str, object]] = {
    "MRNA": {"name": "Moderna, Inc.", "aliases": ["Moderna", "ModernaTX"], "is_biotech": True},
    "BIIB": {"name": "Biogen Inc.", "aliases": ["Biogen"], "is_biotech": True},
    "VRTX": {"name": "Vertex Pharmaceuticals Incorporated", "aliases": ["Vertex"], "is_biotech": True},
    "REGN": {"name": "Regeneron Pharmaceuticals, Inc.", "aliases": ["Regeneron"], "is_biotech": True},
    "GILD": {"name": "Gilead Sciences, Inc.", "aliases": ["Gilead"], "is_biotech": True},
    "AMGN": {"name": "Amgen Inc.", "aliases": ["Amgen"], "is_biotech": True},
    "BMY": {"name": "Bristol Myers Squibb Company", "aliases": ["Bristol Myers Squibb"], "is_biotech": True},
    "PFE": {"name": "Pfizer Inc.", "aliases": ["Pfizer"], "is_biotech": True},
    "LLY": {"name": "Eli Lilly and Company", "aliases": ["Eli Lilly", "Lilly"], "is_biotech": True},
    "CRSP": {"name": "CRISPR Therapeutics AG", "aliases": ["CRISPR Therapeutics"], "is_biotech": True},
    "NTLA": {"name": "Intellia Therapeutics, Inc.", "aliases": ["Intellia"], "is_biotech": True},
    "BEAM": {"name": "Beam Therapeutics Inc.", "aliases": ["Beam Therapeutics"], "is_biotech": True},
}


class TickerResolver:
    def normalize(self, value: object) -> str | None:
        ticker = str(value or "").strip().upper()
        if not ticker or not _TICKER_RE.fullmatch(ticker):
            return None
        return ticker

    def resolve(self, value: object) -> KlineCompany:
        ticker = self.normalize(value)
        if ticker is None:
            raise ValueError("invalid ticker: use 1-16 letters, numbers, dots, or hyphens")
        record = _BIOTECH_UNIVERSE.get(ticker, {})
        return KlineCompany(
            ticker=ticker,
            name=str(record.get("name") or ticker),
            aliases=list(record.get("aliases") or []),
            sector="Healthcare",
            is_biotech=bool(record.get("is_biotech", False)),
        )

    def list_universe(self) -> list[KlineCompany]:
        return [self.resolve(ticker) for ticker in sorted(_BIOTECH_UNIVERSE)]
```

- [ ] Create provider classes. The catalyst provider must overwrite raw event `ticker` with the requested ticker while preserving raw ownership guesses as metadata:

```python
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable

from src.kline.models import KlineDataStatus, KlineEvent
from src.services.event_ingestion_service import get_events_for_ticker


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return [stripped]
            return _as_list(parsed)
        return [stripped]
    return [str(value)]


def _category_for(event_type: str, source: str) -> str:
    if source == "gdelt" or event_type in {"geopolitical", "trade_policy", "sanctions", "macro_economic"}:
        return "macro"
    if event_type in {"fda_decision", "regulatory_change"}:
        return "regulatory"
    if event_type in {"partnership", "financing", "patent", "competitor"}:
        return "corporate"
    return "clinical"


class CatalystEventProvider:
    def __init__(
        self,
        fetch_events: Callable[[str, int], list[dict[str, Any]]] = get_events_for_ticker,
        fetch_statuses: Callable[[str], list[dict[str, Any]]] | None = None,
    ):
        self._fetch_events = fetch_events
        self._fetch_statuses = fetch_statuses

    def load(self, ticker: str) -> tuple[list[KlineEvent], list[KlineDataStatus]]:
        try:
            raw_events = self._fetch_events(ticker, 6)
        except Exception as exc:
            return [], [KlineDataStatus(source="catalysts", status="error", item_count=0, message=str(exc))]

        events = [self._normalize_event(ticker, raw) for raw in raw_events]
        statuses = self._load_source_statuses(ticker, events)
        return events, statuses

    def _load_source_statuses(self, ticker: str, events: list[KlineEvent]) -> list[KlineDataStatus]:
        if self._fetch_statuses is not None:
            rows = self._fetch_statuses(ticker)
            if rows:
                return [
                    KlineDataStatus(
                        source=str(row.get("source")),
                        status="ready" if int(row.get("item_count") or 0) > 0 else "empty",
                        item_count=int(row.get("item_count") or 0),
                        last_fetch_at=row.get("last_fetch_at"),
                    )
                    for row in rows
                ]
        source_counts = Counter(event.source for event in events)
        if source_counts:
            return [
                KlineDataStatus(source=source, status="ready", item_count=count)
                for source, count in sorted(source_counts.items())
            ]
        return [KlineDataStatus(source="catalysts", status="empty", item_count=0)]

    def _normalize_event(self, ticker: str, raw: dict[str, Any]) -> KlineEvent:
        source = str(raw.get("source") or "unknown")
        event_type = str(raw.get("type") or "clinical_readout")
        title = str(raw.get("title") or raw.get("catalyst") or event_type.replace("_", " ").title())
        summary = str(raw.get("summary") or raw.get("catalyst") or title)
        metadata = raw.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {"raw_metadata": metadata}
        source_entity = raw.get("source_entity") or raw.get("sponsor") or raw.get("company") or raw.get("source_company")
        source_ids = _as_list(raw.get("source_ids")) or _as_list(raw.get("nct_id")) or _as_list(raw.get("application_number"))
        raw_ticker = str(raw.get("ticker") or "").strip()
        if raw_ticker and raw_ticker.upper() != ticker.upper():
            metadata = {**metadata, "raw_ticker": raw_ticker}
        return KlineEvent(
            id=str(raw.get("id") or f"{source}-{ticker}-{raw.get('date')}-{title}")[:160],
            ticker=ticker,
            date=str(raw.get("date") or ""),
            type=event_type,
            category=_category_for(event_type, source),
            title=title,
            summary=summary,
            sentiment=str(raw.get("sentiment") or "unknown"),
            priority=int(raw.get("priority") or 3),
            confidence=str(raw.get("confidence") or "medium"),
            source=source,
            source_url=raw.get("source_url") or raw.get("url"),
            source_ids=source_ids,
            source_entity=str(source_entity) if source_entity else None,
            disease_area=raw.get("disease_area"),
            drug_name=raw.get("drug_name"),
            impact_score=raw.get("impact_score") if raw.get("impact_score") is not None else raw.get("price_impact"),
            metadata=metadata,
        )
```

- [ ] Create `src/kline/providers/ohlc_provider.py`:

```python
from src.kline.models import KlineDataStatus, KlinePriceSeries
from src.services.market_data_service import get_ohlc_rows


class OHLCProvider:
    def __init__(self, fetch_rows=get_ohlc_rows):
        self._fetch_rows = fetch_rows

    def load(self, ticker: str) -> tuple[KlinePriceSeries, list[KlineDataStatus]]:
        try:
            rows = self._fetch_rows(ticker, 24)
        except Exception as exc:
            return (
                KlinePriceSeries(
                    rows=[],
                    date_range={"start": None, "end": None},
                    last_close=None,
                    cache_status="error",
                ),
                [KlineDataStatus(source="ohlc", status="error", item_count=0, message=str(exc))],
            )
        date_values = [str(row.get("date")) for row in rows if row.get("date")]
        last_close = float(rows[-1]["close"]) if rows else None
        status = "ready" if rows else "empty"
        return (
            KlinePriceSeries(
                rows=rows,
                date_range={
                    "start": min(date_values) if date_values else None,
                    "end": max(date_values) if date_values else None,
                },
                last_close=last_close,
                cache_status=status,
            ),
            [KlineDataStatus(source="ohlc", status=status, item_count=len(rows))],
        )
```

- [ ] Create `src/kline/providers/backtest_provider.py`:

```python
from src.backtest.runner import load_saved_run


class BacktestResultProvider:
    def __init__(self, load_run=load_saved_run):
        self._load_run = load_run

    def load_last_run(self, ticker: str):
        return None
```

The provider intentionally returns `None` until a stable last-run index exists. The browser keeps the existing local run ID behavior for Phase 1, and `/api/backtest/results/<run_id>` remains the persistence API.

- [ ] Create `src/kline/workspace_service.py` using dependency injection:

```python
from src.kline.models import (
    KlineCapability,
    KlineDataStatus,
    KlineLayer,
    KlinePanelState,
    KlinePriceSeries,
    KlineRangeContext,
    KlineWarning,
    KlineWorkspacePayload,
)
from src.kline.providers.backtest_provider import BacktestResultProvider
from src.kline.providers.catalyst_provider import CatalystEventProvider
from src.kline.providers.ohlc_provider import OHLCProvider
from src.kline.ticker_resolver import TickerResolver


class KlineWorkspaceService:
    def __init__(
        self,
        resolver: TickerResolver | None = None,
        ohlc_provider: OHLCProvider | None = None,
        catalyst_provider: CatalystEventProvider | None = None,
        backtest_provider: BacktestResultProvider | None = None,
    ):
        self.resolver = resolver or TickerResolver()
        self.ohlc_provider = ohlc_provider or OHLCProvider()
        self.catalyst_provider = catalyst_provider or CatalystEventProvider()
        self.backtest_provider = backtest_provider or BacktestResultProvider()

    def build_workspace(self, symbol: str) -> KlineWorkspacePayload:
        company = self.resolver.resolve(symbol)
        price, price_statuses = self.ohlc_provider.load(company.ticker)
        events, event_statuses = self.catalyst_provider.load(company.ticker)
        last_run = self.backtest_provider.load_last_run(company.ticker)
        warnings = self._warnings(price_statuses + event_statuses)
        catalyst_status = "ready" if events else "empty"
        candle_status = "ready" if price.rows else "empty"
        backtest_status = "ready" if last_run else "empty"
        return KlineWorkspacePayload(
            ticker=company.ticker,
            company=company,
            price=price,
            layers=[
                KlineLayer(id="candles", kind="candles", label="Candles", visible_by_default=True, status=candle_status),
                KlineLayer(id="catalysts", kind="catalysts", label="Catalysts", visible_by_default=True, status=catalyst_status, points=events),
                KlineLayer(id="backtest", kind="backtest", label="Backtest", visible_by_default=False, status=backtest_status, series=[]),
            ],
            panels=KlinePanelState(last_backtest_run_id=(last_run or {}).get("run_id") if isinstance(last_run, dict) else None),
            data_status=price_statuses + event_statuses,
            warnings=warnings,
            capabilities=[
                KlineCapability(id="news", enabled=False, phase=2, label="News"),
                KlineCapability(id="macro", enabled=False, phase=2, label="Macro"),
                KlineCapability(id="forecast", enabled=False, phase=3, label="Forecast"),
                KlineCapability(id="range_analysis", enabled=False, phase=3, label="Range Analysis"),
            ],
        )

    def build_range_context(self, symbol: str, start_date: str, end_date: str) -> KlineRangeContext:
        workspace = self.build_workspace(symbol)
        rows = [row for row in workspace.price.rows if start_date <= str(row.get("date")) <= end_date]
        events = [
            event
            for layer in workspace.layers
            if layer.kind == "catalysts"
            for event in layer.points
            if start_date <= event.date <= end_date
        ]
        price_change = None
        if rows:
            first_open = float(rows[0]["open"])
            last_close = float(rows[-1]["close"])
            if first_open:
                price_change = (last_close - first_open) / first_open * 100.0
        return KlineRangeContext(
            ticker=workspace.ticker,
            start_date=start_date,
            end_date=end_date,
            price_change_pct=price_change,
            catalyst_count=len(events),
            catalysts=events,
        )

    def _warnings(self, statuses: list[KlineDataStatus]) -> list[KlineWarning]:
        warnings: list[KlineWarning] = []
        for status in statuses:
            if status.status in {"error", "rate_limited", "stale"}:
                warnings.append(
                    KlineWarning(
                        code=f"{status.source}_{status.status}",
                        source=status.source,
                        message=status.message or f"{status.source} status is {status.status}",
                    )
                )
        return warnings
```

- [ ] Run the unit tests:

```powershell
pytest tests/test_kline_workspace_service.py -q
```

Expected result: all tests in `tests/test_kline_workspace_service.py` pass.

- [ ] Commit the Kline service boundary:

```powershell
git add src/kline tests/test_kline_workspace_service.py
git commit -m "feat: add kline workspace service boundary"
```

Expected output contains `feat: add kline workspace service boundary`.

### Task 3: Fix Event Attribution and Metadata Persistence

**Files:**
- Modify: `src/backtest/events_db.py`
- Modify: `src/services/event_ingestion_service.py`
- Modify: `src/tools/clinical_trials_client.py`
- Modify: `src/tools/openfda_client.py`
- Modify: `tests/test_event_ingestion_service.py`

- [ ] Extend `init_db()` in `src/backtest/events_db.py` with non-destructive columns:

```python
EVENT_EXTRA_COLUMNS = {
    "source_entity": "TEXT",
    "source_url": "TEXT",
    "source_ids": "TEXT",
    "confidence": "TEXT DEFAULT 'medium'",
    "metadata": "TEXT",
}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(biotech_events)").fetchall()
    }
    for column, definition in EVENT_EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE biotech_events ADD COLUMN {column} {definition}")
```

Call `_ensure_columns(conn)` immediately after the `CREATE TABLE IF NOT EXISTS biotech_events` statement and before index creation.

- [ ] Add a serializer in `events_db.py` and use it in `insert_event()` and `insert_events()`:

```python
import json


def _serialize_event(event: dict) -> dict:
    row = dict(event)
    row.setdefault("priority", 3)
    row.setdefault("sentiment", "neutral")
    row.setdefault("price_impact", None)
    row.setdefault("source_entity", None)
    row.setdefault("source_url", None)
    row.setdefault("source_ids", [])
    row.setdefault("confidence", "medium")
    row.setdefault("metadata", {})
    if not isinstance(row["source_ids"], str):
        row["source_ids"] = json.dumps(row["source_ids"], ensure_ascii=False)
    if not isinstance(row["metadata"], str):
        row["metadata"] = json.dumps(row["metadata"], ensure_ascii=False)
    return row
```

Update insert SQL columns to include:

```sql
source_entity, source_url, source_ids, confidence, metadata
```

- [ ] Update `get_events_for_chart()` to decode JSON columns for UI use:

```python
def _decode_event_row(row: dict) -> dict:
    out = dict(row)
    for key, fallback in {"source_ids": [], "metadata": {}}.items():
        value = out.get(key)
        if isinstance(value, str) and value:
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                out[key] = fallback
        elif value is None:
            out[key] = fallback
    return out


def get_events_for_chart(ticker: str) -> list[dict]:
    df = get_events(ticker)
    return [_decode_event_row(row) for row in df.to_dict(orient="records")]
```

- [ ] Add a fetch-log reader for source status:

```python
def get_fetch_log_entries(ticker: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT source, last_fetch_at, item_count
        FROM fetch_log
        WHERE ticker = ?
        ORDER BY source
        """,
        (ticker,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
```

- [ ] Re-export that status through `src/services/event_ingestion_service.py`:

```python
from src.backtest.events_db import get_fetch_log_entries


def get_source_statuses_for_ticker(ticker: str) -> list[dict]:
    init_fetch_log_table()
    return get_fetch_log_entries(ticker)
```

Update `CatalystEventProvider()` default construction after this helper exists:

```python
from src.services.event_ingestion_service import get_events_for_ticker, get_source_statuses_for_ticker


class CatalystEventProvider:
    def __init__(
        self,
        fetch_events: Callable[[str, int], list[dict[str, Any]]] = get_events_for_ticker,
        fetch_statuses: Callable[[str], list[dict[str, Any]]] | None = get_source_statuses_for_ticker,
    ):
        self._fetch_events = fetch_events
        self._fetch_statuses = fetch_statuses
```

- [ ] Change source normalizer signatures:

```python
def normalize_biotech_events(payload: Dict[str, Any], source: str = "openfda", requested_ticker: str | None = None) -> List[Dict[str, Any]]:
```

```python
def normalize_biotech_events(trials: List[Dict[str, str]], source: str = "clinicaltrials", requested_ticker: str | None = None) -> List[Dict[str, any]]:
```

For ClinicalTrials, replace sponsor-derived ticker ownership with:

```python
sponsor = trial.get("sponsor", "UNKNOWN")
ticker = (requested_ticker or sponsor.split()[0] or "UNKNOWN").upper()
source_ids = [trial.get("nct_id")] if trial.get("nct_id") else []
```

Add these fields to each event:

```python
"source_entity": sponsor,
"source_url": trial.get("url"),
"source_ids": source_ids,
"confidence": "high" if source_ids else "medium",
"metadata": {
    "phase": phase,
    "status": trial.get("status"),
    "raw_ticker": sponsor.split()[0] if sponsor else None,
},
```

For openFDA, replace brand-derived ticker ownership with:

```python
openfda = result.get("openfda", {})
brand_names = openfda.get("brand_name", [])
sponsor_name = result.get("sponsor_name")
ticker = (requested_ticker or sponsor_name or (brand_names[0] if brand_names else "UNKNOWN")).upper()
source_ids = [result.get("application_number")] if result.get("application_number") else []
```

Add these fields to each event:

```python
"source_entity": sponsor_name,
"source_url": None,
"source_ids": source_ids,
"confidence": "medium",
"metadata": {
    "brand_names": brand_names,
    "application_number": result.get("application_number"),
    "raw_ticker": brand_names[0] if brand_names else sponsor_name,
},
```

- [ ] Update `src/services/event_ingestion_service.py` so requested ticker is passed into normalizers:

```python
events.extend(normalize_openfda(slice_payload, source="openfda", requested_ticker=ticker))
```

```python
events = normalize_clinical_trials(trials, source="clinicaltrials", requested_ticker=ticker)
```

- [ ] Run event ingestion tests:

```powershell
pytest tests/test_event_ingestion_service.py -q
```

Expected result: all event ingestion tests pass.

- [ ] Commit event attribution and DB metadata:

```powershell
git add src/backtest/events_db.py src/services/event_ingestion_service.py src/tools/clinical_trials_client.py src/tools/openfda_client.py tests/test_event_ingestion_service.py
git commit -m "fix: preserve kline requested ticker attribution"
```

Expected output contains `fix: preserve kline requested ticker attribution`.

### Task 4: Move Kline Routes and Backtest APIs Into a Blueprint

**Files:**
- Create: `src/kline/routes.py`
- Modify: `app.py`
- Modify: `templates/base.html`
- Modify: `tests/test_kline_web_integration.py`

- [ ] Create `src/kline/routes.py`:

```python
import math
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from src.backtest.runner import load_saved_run, normalize_kline_ticker, run_kline_backtest
from src.kline.models import KlineWorkspacePayload
from src.kline.ticker_resolver import TickerResolver
from src.kline.workspace_service import KlineWorkspaceService


kline_bp = Blueprint("kline", __name__)
workspace_service = KlineWorkspaceService()
resolver = TickerResolver()


@kline_bp.get("/kline")
def kline_default():
    symbol = (request.args.get("symbol") or "MRNA").strip().upper() or "MRNA"
    return redirect(url_for("kline.kline_view", symbol=symbol))


@kline_bp.get("/kline/<symbol>")
def kline_view(symbol: str):
    try:
        workspace = workspace_service.build_workspace(symbol)
    except ValueError as exc:
        return render_template("kline_workspace.html", workspace=None, error=str(exc)), 400
    return render_template("kline_workspace.html", workspace=workspace.to_dict(), error=None)


@kline_bp.get("/api/kline/workspace/<symbol>")
def api_kline_workspace(symbol: str):
    try:
        return jsonify(workspace_service.build_workspace(symbol).to_dict())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@kline_bp.get("/api/kline/tickers")
def api_kline_tickers():
    return jsonify([company.__dict__ for company in resolver.list_universe()])


@kline_bp.get("/api/kline/events/<symbol>")
def api_kline_events(symbol: str):
    try:
        workspace = workspace_service.build_workspace(symbol)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    events = [
        event
        for layer in workspace.layers
        if layer.kind == "catalysts"
        for event in layer.points
    ]
    return jsonify([event.__dict__ for event in events])


@kline_bp.get("/api/kline/range-context/<symbol>")
def api_kline_range_context(symbol: str):
    start_date = str(request.args.get("start") or "").strip()
    end_date = str(request.args.get("end") or "").strip()
    if not start_date or not end_date:
        return jsonify({"error": "start and end query parameters are required"}), 400
    try:
        context = workspace_service.build_range_context(symbol, start_date, end_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(context.to_dict())
```

Move the existing `/api/backtest/run` and `/api/backtest/results/<run_id>` implementations from `app.py` into this same blueprint without changing public URLs or validation messages. Keep the validation code intact so existing backtest tests continue to pass.

- [ ] Modify `app.py`:

Remove these imports if no other code uses them:

```python
import math
from datetime import datetime
from src.services.market_data_service import get_ohlc_rows
from src.services.event_ingestion_service import get_events_for_ticker
from src.backtest.runner import run_kline_backtest, load_saved_run, normalize_kline_ticker
```

Add blueprint registration after SocketIO initialization:

```python
from src.kline.routes import kline_bp

app.register_blueprint(kline_bp)
```

Delete these route functions from `app.py`:

```text
kline_default
kline_view
api_backtest_run
api_backtest_result
```

- [ ] Modify `templates/base.html`:

```jinja2
<a href="{{ url_for('kline.kline_default') }}" data-tab="kline" class="nav-link flex items-center space-x-3 px-4 py-3 rounded-lg hover:bg-slate-800 transition-colors {% if kline_active %}bg-slate-800 text-emerald-400{% else %}text-gray-400{% endif %}">
```

- [ ] Update tests that monkeypatch `app_module.run_kline_backtest`, `app_module.load_saved_run`, `app_module.get_ohlc_rows`, or `app_module.get_events_for_ticker` to monkeypatch `src.kline.routes` or `src.kline.routes.workspace_service` instead.

- [ ] Run route tests:

```powershell
pytest tests/test_kline_web_integration.py tests/test_kline_backtest_runner.py -q
```

Expected result: Kline route tests and backtest runner tests pass.

- [ ] Check that `app.py` no longer owns Kline logic:

```powershell
rg -n "kline_default|kline_view|api_backtest_run|api_backtest_result|get_ohlc_rows|get_events_for_ticker|run_kline_backtest|load_saved_run|normalize_kline_ticker" app.py
```

Expected result: no matches.

- [ ] Commit route migration:

```powershell
git add app.py templates/base.html src/kline/routes.py tests/test_kline_web_integration.py
git commit -m "refactor: move kline routes into blueprint"
```

Expected output contains `refactor: move kline routes into blueprint`.

### Task 5: Build the New Workspace Template and Static UI

**Files:**
- Create: `templates/kline_workspace.html`
- Create: `static/kline/workspace.css`
- Create: `static/kline/workspace.js`
- Modify: `src/kline/chart/types.ts`
- Modify: `src/kline/chart/CandlestickChart.tsx`
- Modify: `tests/test_kline_web_integration.py`

- [ ] Create `templates/kline_workspace.html` as a thin shell:

```jinja2
{% extends "base.html" %}

{% block title %}K-Line Workspace{% if workspace %} - {{ workspace.ticker }}{% endif %}{% endblock %}

{% block head %}
  <link rel="stylesheet" href="/static/vendor/pokie-chart.css">
  <link rel="stylesheet" href="/static/kline/workspace.css">
{% endblock %}

{% block content %}
{% if error %}
  <main class="kline-workspace" id="kline-workspace">
    <section class="kline-error">
      <h2>Invalid ticker</h2>
      <p>{{ error }}</p>
      <a href="{{ url_for('kline.kline_default') }}">Open default workspace</a>
    </section>
  </main>
{% else %}
  <main class="kline-workspace" id="kline-workspace" data-ticker="{{ workspace.ticker }}">
    <script id="kline-workspace-data" type="application/json">{{ workspace|tojson }}</script>

    <section class="kline-topbar">
      <div class="ticker-control" data-role="ticker-selector">
        <label for="ticker-search">Ticker</label>
        <form id="ticker-form" class="ticker-form">
          <input id="ticker-search" name="symbol" value="{{ workspace.ticker }}" autocomplete="off" spellcheck="false">
          <button type="submit">Open</button>
        </form>
        <div id="ticker-suggestions" class="ticker-suggestions" aria-live="polite"></div>
      </div>
      <div class="source-strip" id="source-strip"></div>
    </section>

    <section class="company-strip">
      <div>
        <h2 id="company-name">{{ workspace.company.name }}</h2>
        <p>{{ workspace.ticker }} · {{ workspace.company.sector }}</p>
      </div>
      <div class="price-readout">
        <span>Last close</span>
        <strong id="last-close"></strong>
      </div>
      <div class="price-readout">
        <span>Coverage</span>
        <strong id="coverage-range"></strong>
      </div>
      <div class="price-readout">
        <span>Hover</span>
        <strong id="hover-readout">-</strong>
      </div>
    </section>

    <section class="workspace-grid">
      <section class="chart-region">
        <div class="layer-bar" id="layer-bar"></div>
        <div id="kline-container" class="chart-host"></div>
        <div id="range-context" class="range-context" hidden></div>
      </section>

      <aside class="side-panel">
        <div class="panel-tabs" role="tablist">
          <button type="button" data-tab="catalysts" class="is-active">Catalysts</button>
          <button type="button" data-tab="details">Details</button>
          <button type="button" data-tab="backtest">Backtest</button>
          <button type="button" data-tab="status">Status</button>
        </div>
        <section data-panel="catalysts" class="panel-body is-active"></section>
        <section data-panel="details" class="panel-body"></section>
        <section data-panel="backtest" class="panel-body"></section>
        <section data-panel="status" class="panel-body"></section>
      </aside>
    </section>
  </main>
{% endif %}
{% endblock %}

{% block scripts %}
  <script src="/static/vendor/pokie-chart.umd.js"></script>
  <script src="/static/kline/workspace.js"></script>
{% endblock %}
```

- [ ] Create `static/kline/workspace.js` around one `KlineWorkspace` browser module:

```javascript
(function () {
  function readWorkspace() {
    var node = document.getElementById("kline-workspace-data");
    if (!node) {
      return null;
    }
    return JSON.parse(node.textContent || "{}");
  }

  function catalystLayer(workspace) {
    return (workspace.layers || []).find(function (layer) {
      return layer.kind === "catalysts";
    }) || { points: [] };
  }

  function renderChart(workspace, state) {
    var container = document.getElementById("kline-container");
    if (!container || !window.PokieChart || typeof window.PokieChart.render !== "function") {
      return null;
    }
    return window.PokieChart.render(container, {
      ohlcData: workspace.price.rows || [],
      events: state.showCatalysts ? catalystLayer(workspace).points || [] : [],
      highlightedEventId: state.selectedEventId,
      equityCurve: state.equityCurve,
      signals: state.signals,
      trades: state.trades,
      onEventClick: function (event) {
        state.selectedEventId = event.id;
        renderDetails(workspace, state);
        activatePanel("details");
      },
      onHover: function (date, ohlc) {
        var node = document.getElementById("hover-readout");
        node.textContent = ohlc ? date + " $" + Number(ohlc.close).toFixed(2) : "-";
      },
      onRangeSelect: function (range) {
        if (range) {
          loadRangeContext(workspace.ticker, range.startDate, range.endDate);
        }
      }
    });
  }

  function activatePanel(name) {
    document.querySelectorAll("[data-tab]").forEach(function (tab) {
      tab.classList.toggle("is-active", tab.dataset.tab === name);
    });
    document.querySelectorAll("[data-panel]").forEach(function (panel) {
      panel.classList.toggle("is-active", panel.dataset.panel === name);
    });
  }

  async function loadRangeContext(ticker, startDate, endDate) {
    var url = "/api/kline/range-context/" + encodeURIComponent(ticker) + "?start=" + encodeURIComponent(startDate) + "&end=" + encodeURIComponent(endDate);
    var response = await fetch(url);
    var body = await response.json();
    var node = document.getElementById("range-context");
    node.hidden = false;
    node.textContent = startDate + " to " + endDate + ": " + body.catalyst_count + " catalysts";
  }

  function openTicker(symbol) {
    var clean = String(symbol || "").trim().toUpperCase();
    if (clean) {
      window.location.href = "/kline/" + encodeURIComponent(clean);
    }
  }

  function init() {
    var workspace = readWorkspace();
    if (!workspace) {
      return;
    }
    var state = { selectedEventId: null, showCatalysts: true, equityCurve: [], signals: [], trades: [] };
    renderHeader(workspace);
    renderLayerBar(workspace, state);
    renderCatalysts(workspace, state);
    renderDetails(workspace, state);
    renderBacktest(workspace, state);
    renderStatus(workspace);
    var cleanup = renderChart(workspace, state);
    var form = document.getElementById("ticker-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      openTicker(form.elements.symbol.value);
    });
    document.querySelectorAll("[data-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        activatePanel(tab.dataset.tab);
      });
    });
    window.addEventListener("beforeunload", function () {
      if (cleanup) {
        cleanup();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
```

Add these rendering helpers inside the same module:

```javascript
function formatMoney(value) {
  return Number.isFinite(Number(value)) ? "$" + Number(value).toFixed(2) : "-";
}

function renderHeader(workspace) {
  document.getElementById("last-close").textContent = formatMoney(workspace.price.last_close);
  var range = workspace.price.date_range || {};
  document.getElementById("coverage-range").textContent = range.start && range.end ? range.start + " to " + range.end : "-";
  var strip = document.getElementById("source-strip");
  strip.innerHTML = "";
  (workspace.data_status || []).forEach(function (status) {
    var item = document.createElement("span");
    item.className = "source-chip is-" + status.status;
    item.textContent = status.source + ": " + status.status + " (" + status.item_count + ")";
    strip.appendChild(item);
  });
}

function renderLayerBar(workspace, state) {
  var bar = document.getElementById("layer-bar");
  bar.innerHTML = "";
  (workspace.layers || []).forEach(function (layer) {
    var button = document.createElement("button");
    button.type = "button";
    button.dataset.layerKind = layer.kind;
    button.className = layer.visible_by_default ? "is-active" : "";
    button.textContent = layer.label;
    if (layer.kind === "catalysts") {
      button.addEventListener("click", function () {
        state.showCatalysts = !state.showCatalysts;
        button.classList.toggle("is-active", state.showCatalysts);
        renderChart(workspace, state);
      });
    }
    bar.appendChild(button);
  });
  (workspace.capabilities || []).forEach(function (capability) {
    var button = document.createElement("button");
    button.type = "button";
    button.disabled = !capability.enabled;
    button.dataset.capability = capability.id;
    button.textContent = capability.label;
    bar.appendChild(button);
  });
}

function renderCatalysts(workspace, state) {
  var panel = document.querySelector('[data-panel="catalysts"]');
  var events = catalystLayer(workspace).points || [];
  panel.innerHTML = "";
  if (!events.length) {
    panel.textContent = "No catalysts for this ticker.";
    return;
  }
  events.forEach(function (event) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "event-card";
    card.dataset.eventId = event.id;
    card.innerHTML = "<strong>" + event.title + "</strong><span>" + event.date + " · " + event.source + "</span>";
    card.addEventListener("click", function () {
      state.selectedEventId = event.id;
      renderDetails(workspace, state);
      renderChart(workspace, state);
      activatePanel("details");
    });
    panel.appendChild(card);
  });
}

function renderDetails(workspace, state) {
  var panel = document.querySelector('[data-panel="details"]');
  var events = catalystLayer(workspace).points || [];
  var selected = events.find(function (event) {
    return event.id === state.selectedEventId;
  });
  if (!selected) {
    panel.textContent = "Select a catalyst to inspect source metadata.";
    return;
  }
  panel.innerHTML =
    "<h3>" + selected.title + "</h3>" +
    "<p>" + selected.summary + "</p>" +
    "<dl>" +
    "<dt>Source</dt><dd>" + selected.source + "</dd>" +
    "<dt>Source entity</dt><dd>" + (selected.source_entity || "-") + "</dd>" +
    "<dt>Identifiers</dt><dd>" + (selected.source_ids || []).join(", ") + "</dd>" +
    "<dt>Confidence</dt><dd>" + (selected.confidence || "medium") + "</dd>" +
    "</dl>";
}

function renderStatus(workspace) {
  var panel = document.querySelector('[data-panel="status"]');
  panel.innerHTML = "";
  (workspace.data_status || []).forEach(function (status) {
    var row = document.createElement("div");
    row.className = "status-row is-" + status.status;
    row.textContent = status.source + " · " + status.status + " · " + status.item_count;
    panel.appendChild(row);
  });
  (workspace.warnings || []).forEach(function (warning) {
    var row = document.createElement("div");
    row.className = "warning-row";
    row.textContent = warning.message;
    panel.appendChild(row);
  });
}
```

Keep each helper single-purpose and avoid creating a second loader asset.

- [ ] Backtest UI in `workspace.js` must call the existing public APIs:

```javascript
function renderBacktest(workspace, state) {
  var panel = document.querySelector('[data-panel="backtest"]');
  panel.innerHTML =
    '<form id="backtest-form" class="backtest-form">' +
    '<label>Start <input name="start_date" type="date" required></label>' +
    '<label>End <input name="end_date" type="date" required></label>' +
    '<label>Stop Loss Fraction <input name="stop_loss_pct" type="number" step="0.001" value="-0.08"></label>' +
    '<label>Max Position Fraction <input name="max_position_pct" type="number" step="0.001" value="0.2"></label>' +
    '<label>Slippage Fraction <input name="slippage_pct" type="number" step="0.0001" value="0.001"></label>' +
    '<button type="submit">Run Backtest</button>' +
    '</form>' +
    '<div id="backtest-status">No run yet.</div>' +
    '<div id="backtest-results"></div>';
  panel.querySelector("#backtest-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var form = event.currentTarget;
    var status = panel.querySelector("#backtest-status");
    status.textContent = "Running backtest.";
    var response = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: workspace.ticker,
        start_date: form.elements.start_date.value,
        end_date: form.elements.end_date.value,
        stop_loss_pct: Number(form.elements.stop_loss_pct.value),
        max_position_pct: Number(form.elements.max_position_pct.value),
        slippage_pct: Number(form.elements.slippage_pct.value)
      })
    });
    var body = await response.json();
    if (!response.ok) {
      status.textContent = body.error || "Backtest failed.";
      return;
    }
    state.equityCurve = body.equity_curve || [];
    state.signals = body.signals || [];
    state.trades = body.trades || [];
    status.textContent = "Run " + body.run_id + " complete.";
    panel.querySelector("#backtest-results").textContent = JSON.stringify(body.metrics || {}, null, 2);
    renderChart(workspace, state);
  });
}
```

On success, copy `equity_curve`, `signals`, and `trades` into state and call `renderChart(workspace, state)` again.

- [ ] Update chart TypeScript contracts:

```typescript
export interface BiotechEvent {
  id: string;
  ticker: string;
  date: string;
  type: string;
  category?: 'clinical' | 'regulatory' | 'corporate' | 'macro' | 'report';
  title?: string;
  summary?: string;
  priority: 1 | 2 | 3 | 4 | 5;
  disease_area?: string;
  catalyst?: string;
  sentiment: 'positive' | 'negative' | 'neutral' | 'unknown';
  confidence?: 'high' | 'medium' | 'low';
  price_impact?: number;
  impact_score?: number;
  source?: string;
  source_entity?: string;
  source_ids?: string[];
  source_url?: string;
  metadata?: Record<string, unknown>;
}
```

Update marker color logic in `CandlestickChart.tsx` so it can use `event.category` first and fall back to `event.type`. Keep existing backtest overlays intact.

- [ ] Run UI and chart tests:

```powershell
pytest tests/test_kline_web_integration.py tests/test_kline_static_bundle.py -q
Push-Location src\kline
npm run build
Pop-Location
```

Expected result: pytest passes and `npm run build` exits with code 0.

- [ ] Commit the workspace UI:

```powershell
git add templates/kline_workspace.html static/kline src/kline/chart/types.ts src/kline/chart/CandlestickChart.tsx tests/test_kline_web_integration.py static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css
git commit -m "feat: build kline phase1 workspace UI"
```

Expected output contains `feat: build kline phase1 workspace UI`.

### Task 6: Remove Obsolete Kline Surfaces and Dead References

**Files:**
- Delete: `templates/kline.html`
- Delete: `templates/kline_report.html`
- Delete: `templates/partials/kline_chart_assets.html`
- Delete: `templates/partials/kline_chart_runtime.html`
- Delete: `static/vendor/pokie-chart-loader.js`
- Modify: `tests/test_kline_web_integration.py`

- [ ] Delete the obsolete files listed above.

- [ ] Ensure tests no longer read `templates/kline_report.html` directly. Replace any such assertion with checks against `templates/kline_workspace.html` or route-rendered HTML.

- [ ] Verify no dead Kline references remain:

```powershell
rg -n "kline_report|kline_chart_loader|kline_chart_runtime|kline_chart_assets|pokie-chart-loader|request_report|analysis_complete|extract-signals-btn" templates static src tests
```

Expected result: no matches.

- [ ] Verify only intentional Kline route ownership remains:

```powershell
rg -n "@app\\.route\\('/kline|@app\\.route\\(\"/kline|@app\\.route\\('/api/backtest|@app\\.route\\(\"/api/backtest" app.py
```

Expected result: no matches.

- [ ] Run focused tests:

```powershell
pytest tests/test_kline_web_integration.py tests/test_kline_workspace_service.py tests/test_kline_backtest_runner.py -q
```

Expected result: all focused Kline tests pass.

- [ ] Commit cleanup:

```powershell
git add -A templates static src tests
git commit -m "refactor: remove obsolete kline surfaces"
```

Expected output contains `refactor: remove obsolete kline surfaces`.

### Task 7: Final Verification and App Smoke Test

**Files:**
- Read: all changed files

- [ ] Run backend verification:

```powershell
pytest tests/test_kline_workspace_service.py -q
pytest tests/test_kline_web_integration.py -q
pytest tests/test_event_ingestion_service.py -q
pytest tests/test_market_data_service.py -q
pytest tests/test_kline_backtest_runner.py -q
```

Expected result: all commands pass.

- [ ] Run frontend verification:

```powershell
Push-Location src\kline
npm run build
Pop-Location
pytest tests/test_kline_static_bundle.py -q
```

Expected result: Vite build succeeds and static bundle tests pass.

- [ ] Run a local app smoke test:

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5001
```

Expected manual checks:
- `http://127.0.0.1:5001/kline` redirects to `/kline/MRNA`.
- `/kline/MRNA` shows company, ticker, price coverage, chart, catalysts, details, backtest, and status.
- Ticker input opens `/kline/BIIB`.
- Disabled Phase 2/3 capabilities are visible as disabled controls or status items without fake behavior.
- `/api/kline/workspace/MRNA`, `/api/kline/tickers`, `/api/kline/events/MRNA`, and `/api/kline/range-context/MRNA?start=2026-04-20&end=2026-04-20` return JSON.

- [ ] Stop the Flask process after smoke testing.

- [ ] Check the Kline worktree diff only:

```powershell
git status --short
git diff -- app.py templates/base.html templates/kline_workspace.html static/kline src/kline src/services/event_ingestion_service.py src/tools/clinical_trials_client.py src/tools/openfda_client.py src/backtest/events_db.py tests/test_kline_workspace_service.py tests/test_kline_web_integration.py tests/test_event_ingestion_service.py
```

Expected result: no unrelated files are included in the Kline diff.

## Acceptance Checklist

- [ ] `/kline` and `/kline/<symbol>` still work.
- [ ] The page has a visible ticker selector; users do not need to edit the URL.
- [ ] The first viewport identifies ticker, company, last close, date coverage, hover OHLC, and source status.
- [ ] ClinicalTrials and openFDA events keep `ticker` equal to the requested chart ticker.
- [ ] Sponsor, brand, NCT ID, and application number are retained as source metadata.
- [ ] Catalyst layer, selected event details, backtest, and status panels are all present.
- [ ] Phase 2 and Phase 3 contracts exist as disabled capabilities and JSON route contracts.
- [ ] `app.py` no longer contains Kline route functions or Kline business imports.
- [ ] Old Kline templates, partials, loader, report-triggering strings, and dead references are gone.
- [ ] Targeted pytest commands and `npm run build` pass.

## Plan Self-Review Commands

Run these after saving the plan:

```powershell
$pattern = 'TO' + 'DO|T' + 'BD|place' + 'holder|fill' + ' in|\.{3}'
rg -n $pattern docs/superpowers/plans/2026-04-28-kline-phase1-workspace-implementation.md
rg -n "Phase 2|Phase 3|forecast|news|range_analysis" docs/superpowers/plans/2026-04-28-kline-phase1-workspace-implementation.md
rg -n "app.py|kline_report|pokie-chart-loader|workspace_service|requested_ticker" docs/superpowers/plans/2026-04-28-kline-phase1-workspace-implementation.md
```

Expected result:
- First command has no matches.
- Second command shows disabled capabilities, route contracts, and clinical trial sample text only; it must not describe Phase 2 or Phase 3 feature implementation work.
- Third command confirms cleanup, route migration, and attribution coverage.
