# Biotech Quant Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PokieTicker's K-line + particle visualization into Cassandra as a UMD bundle, adapt feature engineering for Parquet-based input, wire Socket.IO bidirectional event flow (K-line anomaly → report, report catalyst → K-line annotation), and scaffold the backtest engine.

**Architecture:** React CandlestickChart compiled via Vite library mode into a UMD bundle, embedded in Cassandra Jinja templates via `window.PokieChart.render()`. Flask/Socket.IO handles bidirectional event routing between the chart and the LangGraph pipeline. Feature engineering modules adapted from SQLite to DataFrame/Parquet input. Backtest engine uses walk-forward validation with multi-pool strategy.

**Tech Stack:** React 19, D3 v7, Vite 7 (library mode), Flask, Socket.IO, pandas, yfinance, Parquet, scikit-learn

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/kline/chart/types.ts` | BiotechEvent, OHLCRow, ChartConfig interfaces |
| `src/kline/chart/index.tsx` | UMD entry point — `window.PokieChart.render()` |
| `src/kline/chart/CandlestickChart.tsx` | Refactored chart (props-driven, no API calls) |
| `src/kline/vite.config.ts` | Vite library mode build config |
| `src/kline/tsconfig.json` | TypeScript config for kline module |
| `templates/kline.html` | Jinja template embedding the UMD bundle |
| `static/vendor/` | Directory for compiled UMD bundle + CSS |
| `src/backtest/__init__.py` | Package init |
| `src/backtest/data_loader.py` | OHLC fetcher (yfinance → Parquet) |
| `src/backtest/events_db.py` | SQLite event store (FDA, clinical, etc.) |
| `src/backtest/features.py` | V1 features adapted for DataFrame input |
| `src/backtest/features_v2.py` | V2 features adapted for DataFrame input |
| `src/backtest/signals.py` | Signal generation (event score × report confidence) |
| `src/backtest/strategy.py` | Position sizing + risk management |
| `src/backtest/metrics.py` | Performance metrics (Sharpe, drawdown, CAR) |
| `src/backtest/runner.py` | Walk-forward backtest orchestrator |

### Modified Files

| File | Change |
|------|--------|
| `src/kline/package.json` | Rename, add vite build script, trim deps |
| `src/kline/CandlestickChart.tsx` | Move to `chart/`, refactor props |
| `src/graph/state.py:21-88` | Add kline-related state fields |
| `src/graph/nodes/extension_handoff_node.py:27-42` | Add `slot_kline` initialization |
| `app.py` | Add Socket.IO event handlers + `/kline` route |

---

## Task 1: Create TypeScript Type Definitions

**Files:**
- Create: `src/kline/chart/types.ts`

- [ ] **Step 1: Create `types.ts` with all shared interfaces**

```typescript
// src/kline/chart/types.ts

export interface OHLCRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BiotechEvent {
  id: string;
  date: string;
  type: 'fda_decision' | 'clinical_readout' | 'partnership' | 'financing' | 'patent' | 'competitor';
  priority: 1 | 2 | 3;
  ticker: string;
  disease_area: string;
  catalyst: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  price_impact?: number;
}

export interface HoverData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  change: number;
}

export interface RangeSelection {
  startDate: string;
  endDate: string;
  priceChange?: number;
  popupX?: number;
  popupY?: number;
}

export interface AnomalySignal {
  ticker: string;
  date: string;
  type: 'volume_spike' | 'gap' | 'particle_cluster';
  magnitude: number;
}

export interface ChartConfig {
  ohlcData: OHLCRow[];
  events: BiotechEvent[];
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
}
```

- [ ] **Step 2: Verify file exists and has no syntax errors**

Run: `cd src/kline && npx tsc --noEmit chart/types.ts --moduleResolution node --esModuleInterop 2>&1 | head -20`

Expected: No errors (or tsc not yet configured — that's fine, we'll add tsconfig in Task 3)

- [ ] **Step 3: Commit**

```bash
git add src/kline/chart/types.ts
git commit -m "feat(kline): add BiotechEvent and ChartConfig type definitions"
```

---

## Task 2: Refactor CandlestickChart to Props-Driven

**Files:**
- Move: `src/kline/CandlestickChart.tsx` → `src/kline/chart/CandlestickChart.tsx`
- Modify: `src/kline/chart/CandlestickChart.tsx`

This is the most critical task. The current component fetches data via axios API calls. We need to change it to accept data via props.

- [ ] **Step 1: Move the file**

```bash
mv src/kline/CandlestickChart.tsx src/kline/chart/CandlestickChart.tsx
```

- [ ] **Step 2: Replace the imports and interfaces block (lines 1-85)**

Remove the existing `OHLCRow`, `Particle`, `HoverData`, `RangeSelection`, `ArticleSelection`, `Props`, `PlacedParticle` interfaces and the axios import. Replace with:

```typescript
// src/kline/chart/CandlestickChart.tsx
import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import type { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal } from './types';

interface PlacedEvent extends BiotechEvent {
  px: number;
  py: number;
  radius: number;
  color: string;
  alpha: number;
}

const EVENT_COLOR: Record<string, string> = {
  fda_decision: '#ff5252',
  clinical_readout: '#00e676',
  partnership: '#00e5ff',
  financing: '#ffd740',
  patent: '#b388ff',
  competitor: '#ff80ab',
};
const EVENT_COLOR_DEFAULT = '#555';

function getEventColor(type: string): string {
  return EVENT_COLOR[type] || EVENT_COLOR_DEFAULT;
}

function getEventRadius(priority: 1 | 2 | 3, priceImpact?: number): number {
  let r = 2;
  if (priority === 1) r += 1.5;
  else if (priority === 2) r += 0.8;
  if (priceImpact != null) r += Math.min(Math.abs(priceImpact) * 10, 1.5);
  return Math.min(r, 5);
}

function getEventAlpha(priority: 1 | 2 | 3): number {
  return priority === 1 ? 0.9 : priority === 2 ? 0.6 : 0.3;
}

interface Props {
  ohlcData: OHLCRow[];
  events: BiotechEvent[];
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
}
```

- [ ] **Step 3: Replace the data-fetching useEffect (lines 196-209)**

Remove the `axios.get` Promise.all block. Replace with a props-driven effect:

```typescript
  useEffect(() => {
    if (!ohlcData || ohlcData.length === 0) return;
    drawChart(ohlcData, events || []);
  }, [ohlcData, events]);
```

- [ ] **Step 4: Update the component signature (line 87)**

Change from:
```typescript
export default function CandlestickChart({ symbol, lockedNewsId, highlightedArticleIds, highlightColor, onHover, onRangeSelect, onArticleSelect, onDayClick }: Props) {
```
To:
```typescript
export default function CandlestickChart({ ohlcData, events, onEventClick, onAnomalyDetected, onHover, onRangeSelect }: Props) {
```

- [ ] **Step 5: Update particle placement to use BiotechEvent**

In the `drawChart` function, replace the `Particle` references. The particle placement loop (around line 310-355) groups by `p.d` (trade_date). Change to group by `event.date`:

```typescript
    const eventsByDate = new Map<string, BiotechEvent[]>();
    for (const evt of events) {
      const arr = eventsByDate.get(evt.date) || [];
      arr.push(evt);
      eventsByDate.set(evt.date, arr);
    }

    const placed: PlacedEvent[] = [];
    const pSpacing = Math.max(4.5, Math.min(7, height / 80));

    for (const [dateStr, evts] of eventsByDate) {
      const ohlcRow = dateToOhlc.get(dateStr);
      if (!ohlcRow) continue;
      const cx = x(ohlcRow.date);
      const baseY = y(ohlcRow.low) + 8;

      const sorted = [...evts].sort((a, b) => a.priority - b.priority);
      sorted.forEach((evt, i) => {
        placed.push({
          ...evt,
          px: cx,
          py: baseY + i * pSpacing,
          radius: getEventRadius(evt.priority, evt.price_impact),
          color: getEventColor(evt.type),
          alpha: getEventAlpha(evt.priority),
        });
      });
    }
```

- [ ] **Step 6: Update drawParticles to use PlacedEvent**

Replace all `PlacedParticle` references with `PlacedEvent`. Remove `lockedNewsId`, `highlightedArticleIds`, `highlightColor` ref logic. Simplify the draw loop to just render events by color/alpha/radius without category filtering.

- [ ] **Step 7: Remove the `loading` state and axios import**

Delete `const [loading, setLoading] = useState(false);` and the `import axios` line. Remove the loading spinner JSX if present.

- [ ] **Step 8: Add anomaly detection in drawChart**

After placing events, add anomaly detection at the end of `drawChart`:

```typescript
    // Anomaly detection: volume spike, gap, or event cluster
    if (onAnomalyDetected) {
      for (const d of data) {
        const avgVol5 = data.slice(Math.max(0, data.indexOf(d) - 5), data.indexOf(d))
          .reduce((s, r) => s + r.volume, 0) / 5;
        const dayEvents = eventsByDate.get(d.dateStr) || [];

        if (d.volume > avgVol5 * 2 && avgVol5 > 0) {
          onAnomalyDetected({ ticker: '', date: d.dateStr, type: 'volume_spike', magnitude: d.volume / avgVol5 });
        }
        if (Math.abs(d.change) > 5) {
          onAnomalyDetected({ ticker: '', date: d.dateStr, type: 'gap', magnitude: Math.abs(d.change) });
        }
        if (dayEvents.length >= 3) {
          onAnomalyDetected({ ticker: '', date: d.dateStr, type: 'particle_cluster', magnitude: dayEvents.length });
        }
      }
    }
```

- [ ] **Step 9: Verify the refactored file compiles**

Run: `cd src/kline && npx tsc --noEmit chart/CandlestickChart.tsx 2>&1 | head -30`

Expected: No errors (or only missing tsconfig — addressed in Task 3)

- [ ] **Step 10: Commit**

```bash
git add src/kline/chart/CandlestickChart.tsx
git add -u src/kline/CandlestickChart.tsx
git commit -m "refactor(kline): props-driven CandlestickChart with BiotechEvent support"
```

---

## Task 3: Vite Library Mode Build Setup

**Files:**
- Modify: `src/kline/package.json`
- Create: `src/kline/vite.config.ts`
- Create: `src/kline/tsconfig.json`

- [ ] **Step 1: Replace `package.json` contents**

```json
{
  "name": "pokie-chart",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "tsc -b && vite build",
    "dev": "vite"
  },
  "dependencies": {
    "d3": "^7.9.0",
    "react": "^19.2.0",
    "react-dom": "^19.2.0"
  },
  "devDependencies": {
    "@types/d3": "^7.4.3",
    "@types/react": "^19.2.5",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^5.1.1",
    "typescript": "~5.9.3",
    "vite": "^7.2.4"
  }
}
```

- [ ] **Step 2: Create `vite.config.ts`**

```typescript
// src/kline/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: resolve(__dirname, 'chart/index.tsx'),
      name: 'PokieChart',
      fileName: (format) => `pokie-chart.${format === 'es' ? 'mjs' : 'umd.js'}`,
    },
    rollupOptions: {
      external: ['react', 'react-dom'],
      output: {
        globals: {
          react: 'React',
          'react-dom': 'ReactDOM',
        },
      },
    },
    outDir: 'dist',
  },
});
```

Note: D3 is NOT externalized — it's bundled into the UMD so the Jinja template only needs React CDN links.

- [ ] **Step 3: Create `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "jsx": "react-jsx",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist",
    "declaration": true
  },
  "include": ["chart/**/*.ts", "chart/**/*.tsx"]
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd src/kline && npx tsc --noEmit 2>&1 | head -20`

Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/kline/package.json src/kline/vite.config.ts src/kline/tsconfig.json
git commit -m "build(kline): add Vite library mode config and tsconfig"
```

---

## Task 4: Create UMD Entry Point

**Files:**
- Create: `src/kline/chart/index.tsx`

- [ ] **Step 1: Create `index.tsx` with `window.PokieChart.render()` API**

```tsx
// src/kline/chart/index.tsx
import { createRoot } from 'react-dom/client';
import CandlestickChart from './CandlestickChart';
import type { ChartConfig } from './types';

export { default as CandlestickChart } from './CandlestickChart';
export type { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, ChartConfig } from './types';

function render(container: HTMLElement, config: ChartConfig): () => void {
  const root = createRoot(container);
  root.render(
    <CandlestickChart
      ohlcData={config.ohlcData}
      events={config.events}
      onEventClick={config.onEventClick}
      onAnomalyDetected={config.onAnomalyDetected}
      onHover={config.onHover}
      onRangeSelect={config.onRangeSelect}
    />
  );
  return () => root.unmount();
}

if (typeof window !== 'undefined') {
  (window as any).PokieChart = { render };
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd src/kline && npx tsc --noEmit 2>&1 | head -20`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/kline/chart/index.tsx
git commit -m "feat(kline): add UMD entry point with window.PokieChart.render API"
```

---

## Task 5: Build UMD Bundle and Deploy to static/vendor

**Files:**
- Build output: `src/kline/dist/`
- Create: `static/vendor/` directory
- Copy: bundle files to `static/vendor/`

- [ ] **Step 1: Install dependencies**

Run: `cd src/kline && npm install`

Expected: `node_modules/` created, no errors

- [ ] **Step 2: Build the UMD bundle**

Run: `cd src/kline && npm run build`

Expected: `dist/pokie-chart.umd.js` and `dist/pokie-chart.mjs` created

- [ ] **Step 3: Create static/vendor and copy bundle**

```bash
mkdir -p static/vendor
cp src/kline/dist/pokie-chart.umd.js static/vendor/
cp src/kline/dist/style.css static/vendor/pokie-chart.css 2>/dev/null || true
```

- [ ] **Step 4: Verify bundle exists**

Run: `ls -la static/vendor/`

Expected: `pokie-chart.umd.js` present, reasonable size (200-500KB with D3 bundled)

- [ ] **Step 5: Commit**

```bash
git add static/vendor/pokie-chart.umd.js static/vendor/pokie-chart.css
git commit -m "build(kline): compile UMD bundle to static/vendor"
```

---

## Task 6: Create Jinja Template for K-line Page

**Files:**
- Create: `templates/kline.html`

- [ ] **Step 1: Create `kline.html`**

```html
<!-- templates/kline.html -->
{% extends "base.html" %}
{% block title %}K-Line · {{ symbol }}{% endblock %}

{% block head %}
<link rel="stylesheet" href="/static/vendor/pokie-chart.css">
<style>
  #kline-container {
    width: 100%;
    height: 600px;
    background: #0d1117;
    border-radius: 8px;
    overflow: hidden;
  }
  .kline-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 0;
  }
  .kline-header h2 {
    margin: 0;
    color: #e6edf3;
  }
  .kline-header .ticker {
    font-size: 1.4em;
    color: #00e5ff;
    font-weight: 700;
  }
</style>
{% endblock %}

{% block content %}
<div class="kline-header">
  <span class="ticker">{{ symbol }}</span>
  <h2>K-Line + Event Overlay</h2>
</div>
<div id="kline-container"></div>

<script src="https://cdn.jsdelivr.net/npm/react@19/umd/react.production.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/react-dom@19/umd/react-dom.production.min.js"></script>
<script src="/static/vendor/pokie-chart.umd.js"></script>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>

<script>
  const socket = io();
  const ticker = '{{ symbol }}';

  const cleanup = PokieChart.render(
    document.getElementById('kline-container'),
    {
      ohlcData: {{ ohlc_json | tojson }},
      events: {{ events_json | tojson }},
      onEventClick: function(evt) {
        socket.emit('request_report', {
          ticker: ticker,
          event_id: evt.id,
          event_type: evt.type,
          date: evt.date,
          catalyst: evt.catalyst
        });
      },
      onAnomalyDetected: function(signal) {
        signal.ticker = ticker;
        socket.emit('anomaly_signal', signal);
      }
    }
  );

  socket.on('report_ready', function(data) {
    console.log('Report ready:', data.report_path);
  });

  socket.on('upcoming_catalysts', function(catalysts) {
    console.log('Upcoming catalysts:', catalysts);
  });
</script>
{% endblock %}
```

- [ ] **Step 2: Verify template syntax**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); env.get_template('kline.html'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add templates/kline.html
git commit -m "feat(kline): add Jinja template with Socket.IO event wiring"
```

---

## Task 7: Extend AgentState with K-line Fields

**Files:**
- Modify: `src/graph/state.py:58-88`

- [ ] **Step 1: Add kline state fields after line 72 (after `analysis_status`)**

Add these fields inside the `AgentState` TypedDict, after the `analysis_status` field:

```python
    # K-line / quant integration
    kline_ohlc_data: Optional[Dict[str, Any]]  # Last-write-wins (ticker → OHLC JSON)
    kline_events: Optional[List[Dict[str, Any]]]  # Last-write-wins (BiotechEvent list)
    kline_anomaly_signals: Annotated[List[Dict[str, Any]], operator.add]  # Accumulated
    kline_report_triggers: Annotated[List[Dict[str, Any]], operator.add]  # Accumulated
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `cd Cassandra && python -c "from src.graph.state import AgentState; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graph/state.py
git commit -m "feat(state): add kline_ohlc_data, kline_events, anomaly/trigger fields"
```

---

## Task 8: Wire extension_handoff for K-line Slot

**Files:**
- Modify: `src/graph/nodes/extension_handoff_node.py:27-42`

- [ ] **Step 1: Add `slot_kline` initialization**

Replace the `extension_handoff_node` function body:

```python
def extension_handoff_node(state: AgentState) -> Dict[str, Any]:
    """Prepare extension slots for future intermediate agents."""
    logger.info("🧩 NODE: EXTENSION HANDOFF")

    existing = state.get("extension_payloads")
    extension_payloads = existing if isinstance(existing, dict) else {}

    extension_payloads.setdefault("slot_a", {})
    extension_payloads.setdefault("slot_b", {})
    extension_payloads.setdefault("slot_c", {})
    extension_payloads.setdefault("slot_kline", {})

    # If anomaly signals arrived from the K-line widget, inject them
    # into the kline slot so downstream agents can reference them.
    anomaly_signals = state.get("kline_anomaly_signals") or []
    if anomaly_signals:
        extension_payloads["slot_kline"] = {
            "anomaly_signals": anomaly_signals,
            "status": "signals_received",
        }
        logger.info(f"🧩 Injected {len(anomaly_signals)} anomaly signals into slot_kline")

    return {
        "extension_payloads": extension_payloads,
        "status": "handoff_complete",
    }
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `cd Cassandra && python -c "from src.graph.nodes.extension_handoff_node import extension_handoff_node; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graph/nodes/extension_handoff_node.py
git commit -m "feat(handoff): add slot_kline with anomaly signal injection"
```

---

## Task 9: Add Flask Routes and Socket.IO Event Handlers

**Files:**
- Modify: `app.py`

This task adds the `/kline/<symbol>` route and Socket.IO event handlers for the bidirectional loop.

- [ ] **Step 1: Add the `/kline/<symbol>` route**

Add after the existing `/graph_view` route (around line 345):

```python
@app.route("/kline/<symbol>")
def kline_view(symbol: str):
    """Render K-line chart with event overlay for a biotech ticker."""
    import yfinance as yf
    import json

    # Fetch OHLC data (last 2 years)
    ticker_data = yf.download(symbol, period="2y", interval="1d", progress=False)
    if ticker_data.empty:
        return f"No data found for {symbol}", 404

    ohlc_rows = []
    for idx, row in ticker_data.iterrows():
        ohlc_rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })

    # Events placeholder — will be populated from events_db later
    events_list = []

    return render_template(
        "kline.html",
        symbol=symbol.upper(),
        ohlc_json=ohlc_rows,
        events_json=events_list,
    )
```

- [ ] **Step 2: Add Socket.IO event handlers for the bidirectional loop**

Add after the existing Socket.IO handlers in `app.py`:

```python
@socketio.on("anomaly_signal")
def handle_anomaly_signal(data):
    """Forward link: K-line anomaly → trigger Cassandra report."""
    logger.info(f"📊 Anomaly signal received: {data}")
    ticker = data.get("ticker", "")
    date = data.get("date", "")
    signal_type = data.get("type", "")
    magnitude = data.get("magnitude", 0)

    user_query = (
        f"Analyze the {signal_type.replace('_', ' ')} anomaly for {ticker} "
        f"on {date} (magnitude: {magnitude:.1f}). "
        f"Identify the catalyst and assess impact on the investment thesis."
    )

    socketio.emit("anomaly_acknowledged", {
        "ticker": ticker,
        "date": date,
        "status": "report_queued",
        "query": user_query,
    })


@socketio.on("request_report")
def handle_request_report(data):
    """Forward link: user clicks event particle → request detailed report."""
    logger.info(f"📊 Report requested for event: {data}")
    event_type = data.get("event_type", "")
    ticker = data.get("ticker", "")
    catalyst = data.get("catalyst", "")
    date = data.get("date", "")

    user_query = (
        f"Generate a detailed analysis of the {event_type.replace('_', ' ')} "
        f"event for {ticker} on {date}: {catalyst}"
    )

    socketio.emit("report_queued", {
        "ticker": ticker,
        "event_id": data.get("event_id"),
        "status": "queued",
        "query": user_query,
    })
```

- [ ] **Step 3: Add `yfinance` to requirements.txt**

Append to `requirements.txt`:

```
yfinance>=0.2.40
pyarrow>=15.0.0
```

- [ ] **Step 4: Verify the app imports correctly**

Run: `cd Cassandra && python -c "import app; print('OK')"`

Expected: `OK` (or expected import warnings for missing env vars — that's fine)

- [ ] **Step 5: Commit**

```bash
git add app.py requirements.txt
git commit -m "feat(app): add /kline route and Socket.IO anomaly/report handlers"
```

---

## Task 10: Backtest Data Loader (yfinance → Parquet)

**Files:**
- Create: `src/backtest/__init__.py`
- Create: `src/backtest/data_loader.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# src/backtest/__init__.py
```

- [ ] **Step 2: Create `data_loader.py`**

```python
# src/backtest/data_loader.py
"""OHLC data fetcher: yfinance → Parquet storage."""

from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ohlc"


def fetch_ohlc(ticker: str, period: str = "10y") -> pd.DataFrame:
    """Download OHLC from yfinance and cache as Parquet."""
    import yfinance as yf

    path = DATA_DIR / f"{ticker}.parquet"
    if path.exists():
        return pd.read_parquet(path)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(ticker, period=period, interval="1d", progress=False)
    if raw.empty:
        return pd.DataFrame()

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "open", "high", "low", "close", "volume"]].dropna()
    df.to_parquet(path, index=False)
    return df


def load_ohlc(ticker: str) -> pd.DataFrame:
    """Load cached Parquet. Returns empty DataFrame if not cached."""
    path = DATA_DIR / f"{ticker}.parquet"
    if not path.exists():
        return fetch_ohlc(ticker)
    return pd.read_parquet(path)


def refresh_ohlc(ticker: str) -> pd.DataFrame:
    """Force re-download and overwrite cache."""
    path = DATA_DIR / f"{ticker}.parquet"
    if path.exists():
        path.unlink()
    return fetch_ohlc(ticker)
```

- [ ] **Step 3: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.data_loader import fetch_ohlc, load_ohlc; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/backtest/__init__.py src/backtest/data_loader.py
git commit -m "feat(backtest): add OHLC data loader with yfinance → Parquet caching"
```

---

## Task 11: Event Database (SQLite Store)

**Files:**
- Create: `src/backtest/events_db.py`

- [ ] **Step 1: Create `events_db.py`**

```python
# src/backtest/events_db.py
"""SQLite event store for biotech catalysts."""

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "events.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create events table if not exists."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS biotech_events (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 3,
            ticker TEXT NOT NULL,
            disease_area TEXT,
            catalyst TEXT,
            sentiment TEXT DEFAULT 'neutral',
            price_impact REAL,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ticker_date
        ON biotech_events(ticker, date)
    """)
    conn.commit()
    conn.close()


def insert_event(event: dict) -> None:
    """Insert a single event. Ignores duplicates by id."""
    conn = _get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO biotech_events
        (id, date, type, priority, ticker, disease_area, catalyst, sentiment, price_impact, source)
        VALUES (:id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment, :price_impact, :source)
    """, event)
    conn.commit()
    conn.close()


def insert_events(events: list[dict]) -> int:
    """Batch insert events. Returns count of inserted rows."""
    conn = _get_conn()
    cur = conn.executemany("""
        INSERT OR IGNORE INTO biotech_events
        (id, date, type, priority, ticker, disease_area, catalyst, sentiment, price_impact, source)
        VALUES (:id, :date, :type, :priority, :ticker, :disease_area, :catalyst, :sentiment, :price_impact, :source)
    """, events)
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


def get_events(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
) -> pd.DataFrame:
    """Query events as DataFrame."""
    conn = _get_conn()
    query = "SELECT * FROM biotech_events WHERE ticker = ?"
    params: list = [ticker]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if event_type:
        query += " AND type = ?"
        params.append(event_type)

    query += " ORDER BY date"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_events_for_chart(ticker: str) -> list[dict]:
    """Return events as list of dicts matching BiotechEvent interface."""
    df = get_events(ticker)
    return df.to_dict(orient="records")
```

- [ ] **Step 2: Verify import and init**

Run: `cd Cassandra && python -c "from src.backtest.events_db import init_db, get_events; init_db(); print('OK')"`

Expected: `OK`, `data/events.db` created

- [ ] **Step 3: Commit**

```bash
git add src/backtest/events_db.py
git commit -m "feat(backtest): add SQLite event store for biotech catalysts"
```

---

## Task 12: Adapt Feature Engineering V1 for DataFrame Input

**Files:**
- Create: `src/backtest/features.py`

This adapts PokieTicker's `backend/ml/features.py` to accept DataFrames instead of querying SQLite.

- [ ] **Step 1: Create `features.py`**

```python
# src/backtest/features.py
"""Feature engineering V1: one row per trading day per ticker.

Adapted from PokieTicker — accepts DataFrames instead of SQLite queries.
"""

import pandas as pd
import numpy as np


FEATURE_COLS = [
    "n_articles", "n_relevant", "n_positive", "n_negative", "n_neutral",
    "sentiment_score", "relevance_ratio", "positive_ratio", "negative_ratio", "has_news",
    "sentiment_score_3d", "sentiment_score_5d", "sentiment_score_10d",
    "positive_ratio_3d", "positive_ratio_5d", "positive_ratio_10d",
    "negative_ratio_3d", "negative_ratio_5d", "negative_ratio_10d",
    "news_count_3d", "news_count_5d", "news_count_10d",
    "sentiment_momentum_3d",
    "ret_1d", "ret_3d", "ret_5d", "ret_10d",
    "volatility_5d", "volatility_10d",
    "volume_ratio_5d", "gap", "ma5_vs_ma20", "rsi_14", "day_of_week",
]


def build_news_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate event data per trade_date into news-like features.

    Args:
        events_df: DataFrame with columns [date, type, priority, sentiment].
                   Can be empty.

    Returns:
        DataFrame indexed by trade_date with news aggregate columns.
    """
    if events_df.empty:
        return pd.DataFrame()

    df = events_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])

    agg = df.groupby("trade_date").agg(
        n_articles=("id", "count"),
        n_positive=("sentiment", lambda x: (x == "positive").sum()),
        n_negative=("sentiment", lambda x: (x == "negative").sum()),
        n_neutral=("sentiment", lambda x: (x == "neutral").sum()),
    ).reset_index()

    agg["n_relevant"] = df.groupby("trade_date")["priority"].apply(
        lambda x: (x <= 2).sum()
    ).values

    total = agg["n_articles"].clip(lower=1)
    agg["sentiment_score"] = (agg["n_positive"] - agg["n_negative"]) / total
    agg["relevance_ratio"] = agg["n_relevant"] / total
    agg["positive_ratio"] = agg["n_positive"] / total
    agg["negative_ratio"] = agg["n_negative"] / total
    agg["has_news"] = 1
    return agg


def build_features(ohlc_df: pd.DataFrame, events_df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix: one row per trading day.

    Args:
        ohlc_df: DataFrame with columns [date, open, high, low, close, volume].
        events_df: DataFrame with columns [id, date, type, priority, sentiment].

    Returns:
        DataFrame with FEATURE_COLS + target columns.
    """
    if ohlc_df.empty or len(ohlc_df) < 30:
        return pd.DataFrame()

    df = ohlc_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    news = build_news_features(events_df)
    if not news.empty:
        df = df.merge(news, on="trade_date", how="left")
    
    news_cols = [
        "n_articles", "n_relevant", "n_positive", "n_negative",
        "n_neutral", "sentiment_score", "relevance_ratio",
        "positive_ratio", "negative_ratio", "has_news",
    ]
    for col in news_cols:
        if col not in df.columns:
            df[col] = 0
    df[news_cols] = df[news_cols].fillna(0)

    # Rolling news features
    for w in [3, 5, 10]:
        df[f"sentiment_score_{w}d"] = df["sentiment_score"].rolling(w, min_periods=1).mean()
        df[f"positive_ratio_{w}d"] = df["positive_ratio"].rolling(w, min_periods=1).mean()
        df[f"negative_ratio_{w}d"] = df["negative_ratio"].rolling(w, min_periods=1).mean()
        df[f"news_count_{w}d"] = df["n_articles"].rolling(w, min_periods=1).sum()
    df["sentiment_momentum_3d"] = df["sentiment_score_3d"] - df["sentiment_score_10d"]

    # Price / technical features (shifted by 1 to prevent leakage)
    close = df["close"]
    df["ret_1d"] = close.pct_change(1).shift(1)
    df["ret_3d"] = close.pct_change(3).shift(1)
    df["ret_5d"] = close.pct_change(5).shift(1)
    df["ret_10d"] = close.pct_change(10).shift(1)

    df["volatility_5d"] = close.pct_change().rolling(5).std().shift(1)
    df["volatility_10d"] = close.pct_change().rolling(10).std().shift(1)

    avg_vol_5 = df["volume"].rolling(5).mean().shift(1)
    df["volume_ratio_5d"] = df["volume"].shift(1) / avg_vol_5.clip(lower=1)

    df["gap"] = (df["open"] / close.shift(1) - 1).shift(1)

    ma5 = close.rolling(5).mean().shift(1)
    ma20 = close.rolling(20).mean().shift(1)
    df["ma5_vs_ma20"] = ma5 / ma20.clip(lower=0.01) - 1

    delta = close.diff().shift(1)
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.clip(lower=1e-10)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    df["day_of_week"] = df["trade_date"].dt.dayofweek

    # Targets
    df["target_t1"] = (close.shift(-1) > close).astype(int)
    df["target_t2"] = (close.shift(-2) > close).astype(int)
    df["target_t3"] = (close.shift(-3) > close).astype(int)
    df["target_t5"] = (close.shift(-5) > close).astype(int)

    df = df.dropna(subset=["ret_10d", "rsi_14"]).reset_index(drop=True)
    return df
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.features import build_features, FEATURE_COLS; print(len(FEATURE_COLS), 'features'); print('OK')"`

Expected: `34 features` then `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/features.py
git commit -m "feat(backtest): adapt V1 feature engineering for DataFrame input"
```

---

## Task 13: Adapt Feature Engineering V2 (Candle Patterns + Market Sentiment)

**Files:**
- Create: `src/backtest/features_v2.py`

- [ ] **Step 1: Create `features_v2.py`**

```python
# src/backtest/features_v2.py
"""Enhanced feature engineering V2: market sentiment + candlestick patterns.

Adapted from PokieTicker — accepts DataFrames instead of SQLite queries.
"""

import pandas as pd
import numpy as np

from src.backtest.features import build_features, FEATURE_COLS


FEATURE_COLS_V2_MARKET = FEATURE_COLS + [
    "mkt_sentiment", "mkt_positive_ratio",
    "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum",
]

FEATURE_COLS_V2_CANDLE = FEATURE_COLS_V2_MARKET + [
    "candle_body_ratio", "candle_bullish", "candle_upper_shadow",
    "candle_lower_shadow", "candle_doji", "candle_hammer",
    "candle_engulfing", "candle_streak",
]


def build_market_sentiment(all_events_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sentiment across ALL tickers per trading date.

    Args:
        all_events_df: DataFrame with columns [date, ticker, sentiment].
    """
    if all_events_df.empty:
        return pd.DataFrame()

    df = all_events_df.copy()
    df["trade_date"] = pd.to_datetime(df["date"])

    agg = df.groupby("trade_date").agg(
        mkt_articles=("id", "count"),
        mkt_positive=("sentiment", lambda x: (x == "positive").sum()),
        mkt_negative=("sentiment", lambda x: (x == "negative").sum()),
        mkt_tickers_active=("ticker", "nunique"),
    ).reset_index()

    total = agg["mkt_articles"].clip(lower=1)
    agg["mkt_sentiment"] = (agg["mkt_positive"] - agg["mkt_negative"]) / total
    agg["mkt_positive_ratio"] = agg["mkt_positive"] / total
    agg["mkt_sentiment_3d"] = agg["mkt_sentiment"].rolling(3, min_periods=1).mean()
    agg["mkt_sentiment_5d"] = agg["mkt_sentiment"].rolling(5, min_periods=1).mean()
    agg["mkt_momentum"] = agg["mkt_sentiment_3d"] - agg["mkt_sentiment_5d"]
    return agg


def add_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Add candlestick pattern features from OHLC data.

    All features shifted by 1 to prevent look-ahead leakage.
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).clip(lower=1e-10)

    df["candle_body_ratio"] = body / rng
    df["candle_bullish"] = (c > o).astype(int)

    upper_shadow = h - pd.concat([o, c], axis=1).max(axis=1)
    df["candle_upper_shadow"] = upper_shadow / rng

    lower_shadow = pd.concat([o, c], axis=1).min(axis=1) - l
    df["candle_lower_shadow"] = lower_shadow / rng

    df["candle_doji"] = (df["candle_body_ratio"] < 0.1).astype(int)
    df["candle_hammer"] = (
        (df["candle_lower_shadow"] > 0.6) & (df["candle_body_ratio"] < 0.3)
    ).astype(int)

    prev_bullish = df["candle_bullish"].shift(1)
    prev_body = body.shift(1)
    df["candle_engulfing"] = (
        (body > prev_body) & (df["candle_bullish"] != prev_bullish)
    ).astype(int).shift(1)

    df["candle_streak"] = (
        df["candle_bullish"].rolling(3, min_periods=1).sum().shift(1)
    )

    for col in [
        "candle_body_ratio", "candle_bullish", "candle_upper_shadow",
        "candle_lower_shadow", "candle_doji", "candle_hammer",
    ]:
        df[col] = df[col].shift(1)

    return df


def build_features_v2(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    all_events_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build enhanced feature matrix with market + candle features.

    Args:
        ohlc_df: Single ticker OHLC data.
        events_df: Events for this ticker.
        all_events_df: Events across ALL tickers (for market sentiment).
    """
    df = build_features(ohlc_df, events_df)
    if df.empty:
        return df

    # Market-wide sentiment
    mkt = build_market_sentiment(all_events_df)
    if not mkt.empty:
        df = df.merge(mkt[["trade_date", "mkt_sentiment", "mkt_positive_ratio",
                           "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum"]],
                      on="trade_date", how="left")
    for col in ["mkt_sentiment", "mkt_positive_ratio",
                "mkt_sentiment_3d", "mkt_sentiment_5d", "mkt_momentum"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0)

    # Candlestick patterns
    df = add_candle_patterns(df)

    # Additional targets for big moves
    close = df["close"]
    ret_t1 = close.shift(-1) / close - 1
    df["target_big1_t1"] = (ret_t1.abs() > 0.01).astype(int)
    df["target_big2_t1"] = (ret_t1.abs() > 0.02).astype(int)
    df["target_up_big_t1"] = (ret_t1 > 0.01).astype(int)
    df["target_down_big_t1"] = (ret_t1 < -0.01).astype(int)

    return df


def get_feature_cols_v2_full(df: pd.DataFrame) -> list[str]:
    """Get all V2 feature columns including any text SVD components."""
    text_cols = [c for c in df.columns if c.startswith("text_svd_")]
    return FEATURE_COLS_V2_CANDLE + text_cols
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.features_v2 import build_features_v2, FEATURE_COLS_V2_CANDLE; print(len(FEATURE_COLS_V2_CANDLE), 'features'); print('OK')"`

Expected: `47 features` then `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/features_v2.py
git commit -m "feat(backtest): adapt V2 features with candle patterns and market sentiment"
```

---

## Task 14: Signal Generation Module

**Files:**
- Create: `src/backtest/signals.py`

- [ ] **Step 1: Create `signals.py`**

```python
# src/backtest/signals.py
"""Signal generation: event score × report confidence → trade signal."""

import pandas as pd
import numpy as np


EVENT_SCORE = {
    "fda_decision": 1.0,
    "clinical_readout": 0.9,
    "partnership": 0.6,
    "financing": 0.4,
    "patent": 0.3,
    "competitor": 0.5,
}

PRIORITY_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.3}

SENTIMENT_DIRECTION = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def score_event(event: dict) -> float:
    """Score a single event: type_weight × priority_weight × sentiment_direction."""
    type_w = EVENT_SCORE.get(event.get("type", ""), 0.3)
    prio_w = PRIORITY_WEIGHT.get(event.get("priority", 3), 0.3)
    sent_d = SENTIMENT_DIRECTION.get(event.get("sentiment", "neutral"), 0.0)
    return type_w * prio_w * sent_d


def generate_signals(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    report_confidence: float = 0.5,
) -> pd.DataFrame:
    """Generate daily trade signals from events + optional report confidence.

    Args:
        ohlc_df: OHLC with 'date' column.
        events_df: Events with 'date', 'type', 'priority', 'sentiment'.
        report_confidence: Cassandra report confidence multiplier [0, 1].

    Returns:
        DataFrame with columns [date, signal, signal_strength].
        signal: 1 (long), -1 (short), 0 (no signal).
    """
    df = ohlc_df[["date"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["raw_score"] = 0.0

    if not events_df.empty:
        ev = events_df.copy()
        ev["date"] = pd.to_datetime(ev["date"])
        ev["score"] = ev.apply(score_event, axis=1)

        daily_score = ev.groupby("date")["score"].sum().reset_index()
        daily_score.columns = ["date", "event_score"]

        df = df.merge(daily_score, on="date", how="left")
        df["event_score"] = df["event_score"].fillna(0)
        df["raw_score"] = df["event_score"] * report_confidence

    # Signal: threshold-based
    df["signal"] = 0
    df.loc[df["raw_score"] > 0.15, "signal"] = 1
    df.loc[df["raw_score"] < -0.15, "signal"] = -1
    df["signal_strength"] = df["raw_score"].abs()

    return df[["date", "signal", "signal_strength"]]
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.signals import generate_signals, score_event; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/signals.py
git commit -m "feat(backtest): add event-driven signal generation module"
```

---

## Task 15: Strategy Module (Position Sizing + Risk Management)

**Files:**
- Create: `src/backtest/strategy.py`

- [ ] **Step 1: Create `strategy.py`**

```python
# src/backtest/strategy.py
"""Strategy execution: position sizing and risk management."""

import pandas as pd
import numpy as np


def apply_strategy(
    ohlc_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    max_position_pct: float = 0.20,
    stop_loss_pct: float = -0.08,
    drawdown_limit_pct: float = -0.15,
    slippage_pct: float = 0.001,
) -> pd.DataFrame:
    """Simulate strategy execution with risk controls.

    Assumptions:
        - T+1 open price execution
        - Single position at a time (long or short)
        - Slippage applied on entry and exit

    Args:
        ohlc_df: OHLC data with 'date', 'open', 'close'.
        signals_df: Signals with 'date', 'signal', 'signal_strength'.
        max_position_pct: Max portfolio allocation per position.
        stop_loss_pct: Single-day stop loss threshold.
        drawdown_limit_pct: Portfolio drawdown threshold for 50% reduction.
        slippage_pct: Slippage per trade (applied to entry price).

    Returns:
        DataFrame with columns [date, position, daily_return, equity, drawdown].
    """
    df = ohlc_df[["date", "open", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.merge(signals_df, on="date", how="left")
    df["signal"] = df["signal"].fillna(0).astype(int)
    df["signal_strength"] = df["signal_strength"].fillna(0)

    n = len(df)
    position = np.zeros(n)
    daily_ret = np.zeros(n)
    equity = np.ones(n)
    peak_equity = 1.0
    drawdown = np.zeros(n)
    scale = 1.0  # risk scaling factor

    for i in range(1, n):
        # Execute signal from previous day at today's open
        prev_signal = df["signal"].iloc[i - 1]
        strength = min(df["signal_strength"].iloc[i - 1], 1.0)
        size = prev_signal * strength * max_position_pct * scale

        position[i] = size

        # Daily return: position × (close/open - 1) - slippage on entry
        if size != 0:
            entry_price = df["open"].iloc[i] * (1 + slippage_pct * np.sign(size))
            price_return = (df["close"].iloc[i] / entry_price - 1) * np.sign(size)
            daily_ret[i] = abs(size) * price_return
        else:
            daily_ret[i] = 0

        # Stop loss check
        if daily_ret[i] < stop_loss_pct * abs(size):
            daily_ret[i] = stop_loss_pct * abs(size)

        equity[i] = equity[i - 1] * (1 + daily_ret[i])
        peak_equity = max(peak_equity, equity[i])
        drawdown[i] = equity[i] / peak_equity - 1

        # Drawdown risk reduction
        if drawdown[i] < drawdown_limit_pct:
            scale = 0.5
        elif drawdown[i] > drawdown_limit_pct * 0.5:
            scale = 1.0

    df["position"] = position
    df["daily_return"] = daily_ret
    df["equity"] = equity
    df["drawdown"] = drawdown

    return df[["date", "position", "daily_return", "equity", "drawdown"]]
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.strategy import apply_strategy; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/strategy.py
git commit -m "feat(backtest): add strategy execution with position sizing and risk controls"
```

---

## Task 16: Performance Metrics Module

**Files:**
- Create: `src/backtest/metrics.py`

- [ ] **Step 1: Create `metrics.py`**

```python
# src/backtest/metrics.py
"""Performance metrics for backtest evaluation."""

import pandas as pd
import numpy as np
from typing import Dict, Any


def compute_metrics(results_df: pd.DataFrame, benchmark_df: pd.DataFrame = None) -> Dict[str, Any]:
    """Compute three-layer performance metrics.

    Args:
        results_df: Strategy results with [date, daily_return, equity, drawdown].
        benchmark_df: Optional benchmark OHLC (e.g., XBI) with [date, close].

    Returns:
        Dict with layer1 (event), layer2 (signal), layer3 (strategy) metrics.
    """
    rets = results_df["daily_return"].dropna()
    equity = results_df["equity"]
    trading_days = 252

    # Layer 3: End-to-end strategy metrics
    total_days = len(rets)
    if total_days < 2:
        return {"error": "insufficient data"}

    ann_return = (equity.iloc[-1] / equity.iloc[0]) ** (trading_days / total_days) - 1
    ann_vol = rets.std() * np.sqrt(trading_days)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0
    max_dd = results_df["drawdown"].min()

    # Win rate
    winning_days = (rets > 0).sum()
    losing_days = (rets < 0).sum()
    active_days = winning_days + losing_days
    win_rate = winning_days / active_days if active_days > 0 else 0

    # Profit factor
    gross_profit = rets[rets > 0].sum()
    gross_loss = abs(rets[rets < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Turnover
    positions = results_df["position"]
    turnover = positions.diff().abs().sum() / total_days * trading_days

    metrics: Dict[str, Any] = {
        "layer3_strategy": {
            "annualized_return": round(ann_return, 4),
            "annualized_volatility": round(ann_vol, 4),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "annual_turnover": round(turnover, 2),
            "total_trading_days": total_days,
        },
    }

    # Benchmark comparison
    if benchmark_df is not None and not benchmark_df.empty:
        bench = benchmark_df.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        merged = results_df.merge(bench[["date", "close"]], on="date", how="inner", suffixes=("", "_bench"))
        if len(merged) > 1:
            bench_ret = merged["close"].pct_change().dropna()
            bench_ann = (merged["close"].iloc[-1] / merged["close"].iloc[0]) ** (trading_days / len(merged)) - 1
            excess = ann_return - bench_ann
            metrics["layer3_strategy"]["benchmark_return"] = round(bench_ann, 4)
            metrics["layer3_strategy"]["excess_return"] = round(excess, 4)

    return metrics


def compute_event_car(
    ohlc_df: pd.DataFrame,
    events_df: pd.DataFrame,
    window_before: int = 5,
    window_after: int = 10,
) -> pd.DataFrame:
    """Compute Cumulative Abnormal Return (CAR) around events.

    Layer 1 metric: event predictability.

    Returns:
        DataFrame with [event_id, event_type, car, t_stat].
    """
    if events_df.empty or ohlc_df.empty:
        return pd.DataFrame()

    ohlc = ohlc_df.copy()
    ohlc["date"] = pd.to_datetime(ohlc["date"])
    ohlc = ohlc.sort_values("date").reset_index(drop=True)
    ohlc["ret"] = ohlc["close"].pct_change()

    results = []
    for _, evt in events_df.iterrows():
        evt_date = pd.to_datetime(evt["date"])
        idx = ohlc.index[ohlc["date"] == evt_date]
        if len(idx) == 0:
            continue
        i = idx[0]

        start = max(0, i - window_before)
        end = min(len(ohlc) - 1, i + window_after)

        window_rets = ohlc["ret"].iloc[start:end + 1].dropna()
        if len(window_rets) < 3:
            continue

        car = window_rets.sum()
        std = window_rets.std()
        t_stat = car / (std * np.sqrt(len(window_rets))) if std > 0 else 0

        results.append({
            "event_id": evt.get("id", ""),
            "event_type": evt.get("type", ""),
            "date": evt["date"],
            "car": round(car, 4),
            "t_stat": round(t_stat, 3),
        })

    return pd.DataFrame(results)
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.metrics import compute_metrics, compute_event_car; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/metrics.py
git commit -m "feat(backtest): add performance metrics with CAR and Sharpe computation"
```

---

## Task 17: Walk-Forward Backtest Runner

**Files:**
- Create: `src/backtest/runner.py`

- [ ] **Step 1: Create `runner.py`**

```python
# src/backtest/runner.py
"""Walk-forward backtest orchestrator with multi-pool validation."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.backtest.data_loader import load_ohlc
from src.backtest.events_db import get_events
from src.backtest.features_v2 import build_features_v2
from src.backtest.signals import generate_signals
from src.backtest.strategy import apply_strategy
from src.backtest.metrics import compute_metrics, compute_event_car

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "backtest_results"


POOLS = {
    "core": {
        "description": "Large-cap biotech (5-15 tickers)",
        "tickers": ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "ALNY", "BMRN"],
    },
    "mid": {
        "description": "XBI/IBB components (30-50 tickers)",
        "tickers": [],  # populated dynamically
    },
}


def run_single_ticker(
    ticker: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    all_events_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Run backtest for a single ticker over a train/test split.

    Returns:
        Dict with ticker, metrics, and equity curve.
    """
    ohlc = load_ohlc(ticker)
    if ohlc.empty:
        return {"ticker": ticker, "error": "no OHLC data"}

    ohlc["date"] = pd.to_datetime(ohlc["date"])
    events = get_events(ticker, start_date=train_start, end_date=test_end)

    if all_events_df is None:
        all_events_df = events

    # Build features on training period
    train_ohlc = ohlc[(ohlc["date"] >= train_start) & (ohlc["date"] <= train_end)]
    train_events = events[pd.to_datetime(events["date"]).between(train_start, train_end)]

    features = build_features_v2(train_ohlc, train_events, all_events_df)
    if features.empty:
        return {"ticker": ticker, "error": "insufficient training data"}

    # Generate signals on test period
    test_ohlc = ohlc[(ohlc["date"] >= test_start) & (ohlc["date"] <= test_end)]
    test_events = events[pd.to_datetime(events["date"]).between(test_start, test_end)]

    signals = generate_signals(test_ohlc, test_events)
    results = apply_strategy(test_ohlc, signals)
    metrics = compute_metrics(results)

    # Event CAR analysis
    car_df = compute_event_car(test_ohlc, test_events)

    return {
        "ticker": ticker,
        "train_period": f"{train_start} → {train_end}",
        "test_period": f"{test_start} → {test_end}",
        "metrics": metrics,
        "event_car_summary": {
            "n_events": len(car_df),
            "mean_car": round(car_df["car"].mean(), 4) if not car_df.empty else None,
            "significant_events": int((car_df["t_stat"].abs() > 1.96).sum()) if not car_df.empty else 0,
        },
    }


def run_walk_forward(
    tickers: list[str],
    start_year: int = 2014,
    end_year: int = 2025,
    train_window: int = 5,
    test_window: int = 1,
) -> dict:
    """Run walk-forward backtest across multiple tickers.

    Walk-forward windows:
        2014-2018 train → 2019 test
        2015-2019 train → 2020 test
        ...

    Returns:
        Dict with per-ticker and aggregate results.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir()

    all_results = []

    for window_start in range(start_year, end_year - train_window - test_window + 2):
        train_start = f"{window_start}-01-01"
        train_end = f"{window_start + train_window - 1}-12-31"
        test_start = f"{window_start + train_window}-01-01"
        test_end = f"{window_start + train_window + test_window - 1}-12-31"

        for ticker in tickers:
            result = run_single_ticker(
                ticker, train_start, train_end, test_start, test_end,
            )
            result["window"] = f"{window_start}-{window_start + train_window + test_window - 1}"
            all_results.append(result)

    # Save results
    output = {
        "run_id": run_id,
        "config": {
            "tickers": tickers,
            "start_year": start_year,
            "end_year": end_year,
            "train_window": train_window,
            "test_window": test_window,
        },
        "results": all_results,
    }

    with open(run_dir / "results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    return output


if __name__ == "__main__":
    result = run_walk_forward(POOLS["core"]["tickers"])
    print(f"Backtest complete: {result['run_id']}")
    print(f"Results saved to: {RESULTS_DIR / result['run_id']}")
```

- [ ] **Step 2: Verify import**

Run: `cd Cassandra && python -c "from src.backtest.runner import run_walk_forward, POOLS; print(POOLS['core']['tickers']); print('OK')"`

Expected: List of core tickers, then `OK`

- [ ] **Step 3: Commit**

```bash
git add src/backtest/runner.py
git commit -m "feat(backtest): add walk-forward backtest runner with multi-pool support"
```

---

## Task 18: Integration Smoke Test

**Files:**
- No new files — verification only

- [ ] **Step 1: Verify all backtest modules import cleanly**

Run:
```bash
cd Cassandra && python -c "
from src.backtest.data_loader import load_ohlc
from src.backtest.events_db import init_db, get_events
from src.backtest.features import build_features, FEATURE_COLS
from src.backtest.features_v2 import build_features_v2, FEATURE_COLS_V2_CANDLE
from src.backtest.signals import generate_signals
from src.backtest.strategy import apply_strategy
from src.backtest.metrics import compute_metrics, compute_event_car
from src.backtest.runner import run_walk_forward
print('All backtest modules OK')
"
```

Expected: `All backtest modules OK`

- [ ] **Step 2: Verify K-line template renders**

Run:
```bash
cd Cassandra && python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
t = env.get_template('kline.html')
print('Template OK')
"
```

Expected: `Template OK`

- [ ] **Step 3: Verify AgentState and extension_handoff**

Run:
```bash
cd Cassandra && python -c "
from src.graph.state import AgentState
from src.graph.nodes.extension_handoff_node import extension_handoff_node
state = {
    'extension_payloads': None,
    'kline_anomaly_signals': [{'ticker': 'MRNA', 'type': 'gap', 'date': '2026-01-15', 'magnitude': 7.2}],
}
result = extension_handoff_node(state)
assert 'slot_kline' in result['extension_payloads']
assert result['extension_payloads']['slot_kline']['status'] == 'signals_received'
print('Extension handoff OK')
"
```

Expected: `Extension handoff OK`

- [ ] **Step 4: Verify UMD bundle exists**

Run: `ls -la static/vendor/pokie-chart.umd.js`

Expected: File exists with reasonable size

- [ ] **Step 5: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test: verify full integration of kline + backtest modules"
```

---

## Summary

| Task | Component | Est. Time |
|------|-----------|-----------|
| 1 | TypeScript types | 2 min |
| 2 | CandlestickChart refactor | 5 min |
| 3 | Vite build setup | 3 min |
| 4 | UMD entry point | 3 min |
| 5 | Build + deploy bundle | 3 min |
| 6 | Jinja template | 3 min |
| 7 | AgentState extension | 2 min |
| 8 | extension_handoff wiring | 3 min |
| 9 | Flask routes + Socket.IO | 4 min |
| 10 | Data loader (yfinance) | 3 min |
| 11 | Event database | 3 min |
| 12 | Features V1 | 4 min |
| 13 | Features V2 | 4 min |
| 14 | Signal generation | 3 min |
| 15 | Strategy execution | 4 min |
| 16 | Performance metrics | 4 min |
| 17 | Backtest runner | 4 min |
| 18 | Integration smoke test | 3 min |
| **Total** | | **~60 min** |
