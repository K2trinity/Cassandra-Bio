# KLine Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PokieTicker-like K-line visualization workspace that shows OHLC candles and biotech event markers without depending on the disease report pipeline.

**Architecture:** Keep `/kline/<symbol>` as the visualization route. The route loads OHLC rows from `market_data_service` and event rows from `event_ingestion_service`, then renders a chart-first page with Events and Backtest panels. Remove K-line page coupling to `/api/analyze`; ticker investigation is outside this feature.

**Tech Stack:** Flask, Jinja templates, TypeScript, React, D3, Vite, pytest.

---

## File Structure

- `templates/kline_report.html`: K-line workspace layout, controls, and browser-side state.
- `src/kline/chart/types.ts`: chart data contracts used by the React chart bundle.
- `src/kline/chart/CandlestickChart.tsx`: candle chart, event marker, hover, and empty-state rendering.
- `tests/test_kline_web_integration.py`: Flask route and template contract tests.
- `src/kline/package.json`: existing build command used for TypeScript validation.

No disease report files are modified in this plan.

---

### Task 1: Make KLine Visualization Independent From Report Analysis

**Files:**
- Modify: `tests/test_kline_web_integration.py`
- Modify: `templates/kline_report.html`

- [ ] **Step 1: Replace the report-coupling test with a failing independence test**

In `tests/test_kline_web_integration.py`, replace `test_kline_page_uses_main_analysis_event_flow` with:

```python
def test_kline_page_is_independent_from_report_analysis(monkeypatch):
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return [
            {
                "date": "2026-04-20",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 1200000,
            }
        ]

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return [
            {
                "id": "evt_001",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": ticker,
                "disease_area": "Alzheimer Disease",
                "catalyst": "Phase 3 readout",
                "sentiment": "positive",
                "source": "clinicaltrials",
            }
        ]

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "/api/analyze" not in html
    assert "analysis_complete" not in html
    assert "request_report" not in html
    assert 'data-tab="report"' not in html
    assert "extract-signals-btn" not in html
    assert 'data-tab="events"' in html
    assert 'data-tab="backtest"' in html
```

- [ ] **Step 2: Replace the tab shell test with a two-tab contract**

In the same file, replace `test_kline_template_has_three_tab_shell` with:

```python
def test_kline_template_has_visualization_and_backtest_tabs(monkeypatch):
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return []

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return []

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-tab="events"' in html
    assert 'data-tab="backtest"' in html
    assert 'data-tab="report"' not in html
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```powershell
pytest tests/test_kline_web_integration.py -q --basetemp .pytest_tmp_kline_visual
```

Expected:

```text
FAILED tests/test_kline_web_integration.py::test_kline_page_is_independent_from_report_analysis
FAILED tests/test_kline_web_integration.py::test_kline_template_has_visualization_and_backtest_tabs
```

The failure should mention existing `/api/analyze`, `analysis_complete`, `data-tab="report"`, or `extract-signals-btn` content.

- [ ] **Step 4: Remove report controls from the KLine template**

In `templates/kline_report.html`, make the tab controls exactly:

```html
<div class="workspace-tabs">
  <button type="button" id="events-tab" class="workspace-tab is-active" role="tab" aria-selected="true" data-tab="events">Events</button>
  <button type="button" id="backtest-tab" class="workspace-tab" role="tab" aria-selected="false" data-tab="backtest">Backtest</button>
</div>
```

Remove the entire report panel section with `id="report-panel"`. Remove the `extract-signals-btn` button from the backtest panel.

- [ ] **Step 5: Remove report-analysis JavaScript from the KLine template**

In `templates/kline_report.html`, remove these constants and functions:

```javascript
const reportContent = document.getElementById('report-content');
const overviewButton = document.getElementById('overview-investigation-btn');
const extractSignalsButton = document.getElementById('extract-signals-btn');
```

Remove these functions and event handlers:

```javascript
function renderPanel(sections) {}
function renderInfo(title, message) {}
function showExtractSignalsCTA(visible) {}
function renderProgress(data) {}
function renderAnalysis(data) {}
function stopStatusPolling() {}
async function pollStatusOnce() {}
function startStatusPolling(taskId) {}
function describeEvent(eventItem) {}
function buildOverviewQuery() {}
function buildEventQuery(eventItem) {}
async function queueAnalysis(query, contextLabel) {}
function connectSocket() {}
overviewButton.addEventListener('click', function() {});
extractSignalsButton.addEventListener('click', async function() {});
```

In the `event-investigate` click handler, replace the old report queue behavior with marker highlighting only:

```javascript
button.addEventListener('click', function(event) {
  event.stopPropagation();
  const eventId = button.dataset.investigateId;
  const targetEvent = pageState.events.find(function(item) {
    return item.id === eventId;
  });

  if (!targetEvent) {
    return;
  }

  pageState.highlightedEventId = targetEvent.id;
  renderEventsList();
  renderChart();
  scrollToEventCard(targetEvent.id);
});
```

Remove the final `renderInfo(infoPayload)` and `connectSocket()` startup calls. Keep:

```javascript
initializeTabs();
initializeResizeAndCollapse();
initializeBacktestDefaults();
populateFilterOptions();
attachFilterHandlers();
renderEventsList();
renderChart();
setActiveTab('events');
```

- [ ] **Step 6: Run the focused tests and verify they pass**

Run:

```powershell
pytest tests/test_kline_web_integration.py -q --basetemp .pytest_tmp_kline_visual
```

Expected:

```text
9 passed
```

- [ ] **Step 7: Commit**

Run:

```powershell
git status --short
git add tests/test_kline_web_integration.py templates/kline_report.html
git commit -m "refactor: decouple kline visualization from report analysis"
```

Expected:

```text
[branch commit] refactor: decouple kline visualization from report analysis
```

---

### Task 2: Add Event Summary And Legend To The KLine Workspace

**Files:**
- Modify: `tests/test_kline_web_integration.py`
- Modify: `templates/kline_report.html`

- [ ] **Step 1: Add a failing template contract test**

Append to `tests/test_kline_web_integration.py`:

```python
def test_kline_template_renders_event_summary_and_legend(monkeypatch):
    def fake_get_ohlc_rows(ticker: str, max_age_hours: int = 24):
        return [
            {
                "date": "2026-04-20",
                "open": 101.0,
                "high": 104.0,
                "low": 100.0,
                "close": 103.0,
                "volume": 1200000,
            }
        ]

    def fake_get_events_for_ticker(ticker: str, max_age_hours: int = 6):
        return [
            {
                "id": "evt_001",
                "date": "2026-04-20",
                "type": "clinical_readout",
                "priority": 1,
                "ticker": ticker,
                "disease_area": "Alzheimer Disease",
                "catalyst": "Phase 3 readout",
                "sentiment": "positive",
                "source": "clinicaltrials",
            }
        ]

    monkeypatch.setattr(app_module, "get_ohlc_rows", fake_get_ohlc_rows)
    monkeypatch.setattr(app_module, "get_events_for_ticker", fake_get_events_for_ticker)

    client = app.test_client()
    response = client.get("/kline/MRNA")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="event-summary-bar"' in html
    assert 'id="event-legend"' in html
    assert "renderEventSummary" in html
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/test_kline_web_integration.py::test_kline_template_renders_event_summary_and_legend -q --basetemp .pytest_tmp_kline_visual
```

Expected:

```text
FAILED tests/test_kline_web_integration.py::test_kline_template_renders_event_summary_and_legend
```

- [ ] **Step 3: Add summary and legend containers**

In `templates/kline_report.html`, place this block above `<div id="events-list" class="events-list"></div>`:

```html
<div id="event-summary-bar" class="event-summary-bar"></div>
<div id="event-legend" class="event-legend"></div>
```

Add CSS in the existing KLine `<style>` block:

```css
.event-summary-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.event-summary-item {
  border: 1px solid #243244;
  background: #0b1220;
  border-radius: 8px;
  padding: 8px 10px;
}

.event-summary-label {
  color: #94a3b8;
  font-size: 0.72rem;
  text-transform: uppercase;
}

.event-summary-value {
  color: #e5e7eb;
  font-size: 1rem;
  font-weight: 700;
  margin-top: 2px;
}

.event-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 2px 0;
}

.legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #cbd5e1;
  font-size: 0.78rem;
}

.legend-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  display: inline-block;
}
```

- [ ] **Step 4: Add deterministic summary rendering**

In the script section, add element references:

```javascript
const eventSummaryBar = document.getElementById('event-summary-bar');
const eventLegend = document.getElementById('event-legend');
```

Add these functions near `renderEventsList()`:

```javascript
function countEventsBy(fieldName) {
  const counts = {};
  pageState.events.forEach(function(eventItem) {
    const key = safeEventText(eventItem && eventItem[fieldName], 'unknown');
    counts[key] = (counts[key] || 0) + 1;
  });
  return counts;
}

function renderEventSummary() {
  const events = pageState.events;
  const positive = events.filter(function(item) { return item.sentiment === 'positive'; }).length;
  const negative = events.filter(function(item) { return item.sentiment === 'negative'; }).length;
  const highPriority = events.filter(function(item) { return Number(item.priority || 3) === 1; }).length;

  eventSummaryBar.innerHTML = [
    ['Total Events', events.length],
    ['Positive', positive],
    ['Negative', negative],
    ['Priority 1', highPriority]
  ].map(function(item) {
    return '<div class="event-summary-item">' +
      '<div class="event-summary-label">' + escapeHtml(item[0]) + '</div>' +
      '<div class="event-summary-value">' + escapeHtml(item[1]) + '</div>' +
      '</div>';
  }).join('');

  const typeCounts = countEventsBy('type');
  eventLegend.innerHTML = Object.keys(typeCounts).sort().map(function(typeName) {
    return '<span class="legend-pill">' +
      '<span class="legend-dot" style="background:' + escapeHtml(eventColor(typeName)) + '"></span>' +
      escapeHtml(formatEventType(typeName)) + ' (' + escapeHtml(typeCounts[typeName]) + ')' +
      '</span>';
  }).join('');
}

function eventColor(typeName) {
  const colors = {
    fda_decision: '#00e676',
    clinical_readout: '#00e5ff',
    partnership: '#667eea',
    financing: '#ffd700',
    patent: '#ff9800',
    competitor: '#ff5252',
    geopolitical: '#a78bfa',
    trade_policy: '#38bdf8',
    sanctions: '#fb7185',
    regulatory_change: '#f59e0b',
    macro_economic: '#94a3b8'
  };
  return colors[typeName] || '#64748b';
}
```

Call `renderEventSummary()` after `renderEventsList()` during startup and after filters or events change:

```javascript
renderEventsList();
renderEventSummary();
renderChart();
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_kline_web_integration.py -q --basetemp .pytest_tmp_kline_visual
```

Expected:

```text
10 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git status --short
git add tests/test_kline_web_integration.py templates/kline_report.html
git commit -m "feat: add kline event summary legend"
```

Expected:

```text
[branch commit] feat: add kline event summary legend
```

---

### Task 3: Align Chart Event Colors With The Event Contract

**Files:**
- Modify: `src/kline/chart/CandlestickChart.tsx`

- [ ] **Step 1: Run TypeScript build before editing**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 2: Extend the event color map**

In `src/kline/chart/CandlestickChart.tsx`, replace `EVENT_TYPE_COLOR` with:

```typescript
const EVENT_TYPE_COLOR: Record<string, string> = {
  fda_decision: '#00e676',
  clinical_readout: '#00e5ff',
  partnership: '#667eea',
  financing: '#ffd700',
  patent: '#ff9800',
  competitor: '#ff5252',
  geopolitical: '#a78bfa',
  trade_policy: '#38bdf8',
  sanctions: '#fb7185',
  regulatory_change: '#f59e0b',
  macro_economic: '#94a3b8',
};

const EVENT_TYPE_COLOR_DEFAULT = '#64748b';
```

- [ ] **Step 3: Run TypeScript build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 4: Commit**

Run:

```powershell
git status --short
git add src/kline/chart/CandlestickChart.tsx static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css static/vendor/pokie-chart-loader.js
git commit -m "feat: align kline event marker colors"
```

Expected:

```text
[branch commit] feat: align kline event marker colors
```

If the build writes only `src/kline/dist`, copy or run the existing project bundle step that updates `static/vendor/pokie-chart.umd.js` before committing. The committed browser bundle must match the TypeScript source used by the page.

---

### Task 4: Verify KLine Visualization End To End

**Files:**
- No source files.

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
pytest tests/test_kline_web_integration.py tests/test_market_data_service.py tests/test_event_ingestion_service.py -q --basetemp .pytest_tmp_kline_visual
```

Expected:

```text
Command exits with code 0 and the pytest summary contains only passed tests for:
tests/test_kline_web_integration.py
tests/test_market_data_service.py
tests/test_event_ingestion_service.py
```

- [ ] **Step 2: Run TypeScript build**

Run:

```powershell
npm --prefix src/kline run build
```

Expected:

```text
vite v
✓ built
```

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected:

```text
No output.
```

- [ ] **Step 4: Remove temporary pytest directory**

Run:

```powershell
$repo = (Resolve-Path -LiteralPath '.').Path
$target = (Resolve-Path -LiteralPath '.pytest_tmp_kline_visual' -ErrorAction SilentlyContinue)
if ($target) {
  if (-not $target.Path.StartsWith($repo)) { throw "Refusing to remove path outside repository root: $($target.Path)" }
  Remove-Item -LiteralPath $target.Path -Recurse -Force
}
```

Expected:

```text
No output.
```

- [ ] **Step 5: Commit verification-only bundle updates if needed**

Run:

```powershell
git status --short
```

Expected:

```text
No uncommitted KLine visualization files, or only build artifacts that correspond to the committed TypeScript changes.
```

If build artifacts remain because the bundling step updated static files, commit only those files:

```powershell
git add static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css static/vendor/pokie-chart-loader.js
git commit -m "build: refresh kline chart bundle"
```
