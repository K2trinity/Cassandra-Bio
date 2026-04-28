# KLine Backtest And Report Narratives Design

Date: 2026-04-28

## Purpose

Cassandra needs two focused improvements without reopening the disease report
pipeline architecture:

1. Build a PokieTicker-like K-line workspace that visualizes OHLC candles and
   biotech event markers.
2. Add a separate backtest workflow that computes strategy results and renders
   an equity curve.
3. Add Gemini-generated descriptive chapter summaries to disease reports, with
   Chinese and English output options.

The K-line workspace and backtest are market-data features. They must not depend
on the disease report package or mutate report data. The Gemini narrative layer
is a report presentation feature. It must not extract facts, classify risk,
generate events, or change structured report data.

## Architecture Decision

Use two independent feature paths:

```text
KLine Visualization
  -> OHLC service
  -> Event ingestion service
  -> Candlestick chart

Backtest
  -> Existing event store
  -> Signal generation
  -> Strategy runner
  -> Metrics + equity curve + event CAR

Disease Report Narrative
  -> DiseaseReportPackage
  -> Gemini narrative service
  -> DiseaseReportIRBuilder
  -> Renderers
```

This keeps the current disease report pipeline intact:

```text
DiseaseReportOrchestrator
  -> DiseaseReportPackageBuilder
  -> DiseaseReportNarrativeService
  -> DiseaseReportIRBuilder
  -> DiseaseReportRendererAdapter
```

Gemini receives chapter-scoped structured data and returns only strings. The
structured package remains authoritative.

## KLine Visualization

The visualization feature owns the PokieTicker-style chart experience. It loads
market data and event markers, then renders them in the browser.

Production route:

```text
GET /kline/<symbol>
```

Current source modules remain the right ownership boundaries:

- `src/services/market_data_service.py`: loads and refreshes OHLC rows.
- `src/services/event_ingestion_service.py`: loads and caches biotech events.
- `src/backtest/events_db.py`: stores normalized event rows.
- `src/kline/chart/CandlestickChart.tsx`: renders candles, event markers,
  hover state, range selection, anomaly markers, and optional overlays.
- `templates/kline_report.html`: page shell and controls.

The K-line chart consumes a stable frontend contract:

```typescript
interface OHLCRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface BiotechEvent {
  id: string;
  date: string;
  type: string;
  priority: 1 | 2 | 3;
  ticker: string;
  disease_area: string;
  catalyst: string;
  sentiment: "positive" | "negative" | "neutral";
  price_impact?: number;
  source?: string;
}
```

The visualization must be usable without running a report. If OHLC data or event
data is empty, the page should still render a clear empty state and keep the
backtest controls available when a valid date range exists.

## Backtest Workflow

The backtest feature is separate from the chart data load. It runs only when the
user submits the backtest form.

Production endpoint:

```text
POST /api/backtest/run
```

Current backend flow:

```text
run_kline_backtest()
  -> load_ohlc()
  -> get_events()
  -> generate_signals()
  -> apply_strategy()
  -> compute_metrics()
  -> compute_event_car()
```

The response should remain chart-ready. The existing fields stay:

```json
{
  "run_id": "20260428_120000_ab12cd34",
  "ticker": "BIIB",
  "start_date": "2024-01-01",
  "end_date": "2026-04-28",
  "metrics": {},
  "equity_curve": [],
  "event_car": []
}
```

The backtest response will add optional chart overlays. The fields are optional
for backward compatibility, but when present they use this shape:

```json
{
  "signals": [
    {
      "date": "2026-04-20",
      "signal": 1,
      "signal_strength": 0.36,
      "source_event_ids": []
    }
  ],
  "trades": [
    {
      "entry_date": "2026-04-21",
      "exit_date": "2026-04-25",
      "direction": "long",
      "size": 0.12,
      "entry_price": 101.5,
      "exit_price": 108.2,
      "pnl_pct": 0.066
    }
  ]
}
```

The frontend renders:

- Event markers on the K-line chart.
- Optional signal markers after a backtest run.
- Equity curve on a secondary y-axis.
- Backtest metrics in the backtest panel.
- Event CAR rows in the backtest panel.

Backtest must not call Gemini. Signal generation stays deterministic and based
on existing event fields.

## KLine And Report Boundary

The K-line feature should not call the disease report endpoint as part of the
normal visualization or backtest workflow.

The existing `/api/analyze` endpoint now represents the disease report pipeline.
Ticker-level event investigation should be kept out of the K-line core path. If
the product later needs event investigation, it should use a dedicated endpoint:

```text
POST /api/kline/investigate
```

That future endpoint is outside this design. The current scope is visualization
and backtest.

## Gemini Chapter Narratives

The report narrative feature adds one optional presentation layer after the
typed disease report package is built.

New module:

```text
src/reports/disease/narrative.py
```

New model:

```python
class DiseaseChapterNarratives(BaseModel):
    executive_summary: str = ""
    clinical_trial_and_pipeline_landscape: str = ""
    pipeline_timeline_and_competition_risk: str = ""
    language: Literal["zh", "en"] = "zh"
```

The service contract is:

```python
class DiseaseReportNarrativeService:
    def generate(
        self,
        package: DiseaseReportPackage,
        language: Literal["zh", "en"] = "zh",
    ) -> DiseaseChapterNarratives:
        """Return chapter prose without mutating the package."""
```

The service uses `create_report_client()` from `src.llms` and calls
`generate_json()` so the output shape is constrained. It must not return IR
blocks. It returns only strings.

## Narrative Language Option

The narrative layer supports:

```text
zh: Chinese summaries
en: English summaries
```

Default:

```text
REPORT_NARRATIVE_LANGUAGE=zh
```

Runtime request override:

```json
{
  "query": "Alzheimer disease report",
  "narrative_language": "en"
}
```

The language option affects only generated descriptive paragraphs. It does not
translate table headers, alter source data, or change risk labels unless a
separate future localization design explicitly enables that.

## Narrative Prompt Boundary

Gemini receives chapter-scoped data, not unrestricted report text. The system
instruction must state:

```text
Use only the supplied JSON data.
Do not infer missing facts.
Do not create trials, sponsors, dates, risk labels, endpoints, or numeric values.
Do not classify risk.
Do not modify field values.
Return strict JSON only.
```

For Chinese output, ask for concise Chinese prose. For English output, ask for
concise English prose. The target length should be short enough to improve
readability without replacing the structured tables:

```text
80-180 Chinese characters or 60-120 English words per chapter.
```

## Narrative Inputs

Executive summary payload:

```json
{
  "disease_name": "Alzheimer Disease",
  "retained_count": 50,
  "rejected_count": 12,
  "latest_study_first_posted": "2026-04-20",
  "status_distribution": {
    "RECRUITING": 18,
    "COMPLETED": 12,
    "ACTIVE_NOT_RECRUITING": 8
  },
  "top_sponsors": ["Eli Lilly and Company", "Biogen", "Roche"]
}
```

Clinical trial and pipeline landscape payload:

```json
{
  "disease_name": "Alzheimer Disease",
  "trial_count": 2,
  "records": [
    {
      "study_title": "A Study of Donanemab in Early Symptomatic Alzheimer Disease",
      "nct_number": "NCT00000001",
      "status": "RECRUITING",
      "conditions": ["Alzheimer Disease"],
      "interventions": ["Donanemab"],
      "sponsor": "Eli Lilly and Company",
      "study_type": "INTERVENTIONAL"
    }
  ]
}
```

Pipeline timeline and competition risk payload:

```json
{
  "disease_name": "Alzheimer Disease",
  "risk_records": [
    {
      "nct_number": "NCT00000001",
      "study_title": "A Study of Donanemab in Early Symptomatic Alzheimer Disease",
      "sponsor": "Eli Lilly and Company",
      "status": "RECRUITING",
      "intervention_category": "amyloid antibody",
      "timeline_signal": "Low",
      "timeline_evidence": "Study first posted 2026-04-20; status RECRUITING; age 0.0 years.",
      "competition_signal": "Medium",
      "competition_evidence": "5 retained Alzheimer Disease studies share intervention category amyloid antibody."
    }
  ],
  "risk_distribution": {
    "timeline": {"Low": 12, "Medium": 7, "High": 3},
    "competition": {"Low": 9, "Medium": 10, "High": 3}
  }
}
```

The payload is derived from `DiseaseReportPackage`. It does not add new facts.

## IR Insertion

`DiseaseReportIRBuilder.build()` should accept an optional narratives object:

```python
def build(
    self,
    package: DiseaseReportPackage,
    narratives: DiseaseChapterNarratives | None = None,
) -> dict:
    """Build report IR with optional presentation-only narratives."""
```

Each chapter inserts the narrative after the heading and before the table or KPI
blocks:

```text
heading
Gemini narrative paragraph if present
deterministic context paragraph or KPI blocks
table
```

If a narrative field is empty, the builder keeps the current deterministic
paragraph. Renderers continue to consume normal paragraph blocks.

## Error Handling

Gemini is optional for report completion.

Failure behavior:

- Gemini timeout, API error, invalid JSON, missing fields, or empty text returns
  an empty `DiseaseChapterNarratives`.
- The report still renders with deterministic paragraphs.
- The failure is logged as a warning.
- No exception from the narrative layer should fail the report unless a future
  strict mode is explicitly enabled.

KLine error behavior:

- Missing OHLC data renders an empty chart state.
- Missing events renders an empty event list.
- Backtest API validation errors return `400` with a readable error.
- Backtest calculation errors return `400` without changing stored events.

## Testing Strategy

KLine tests:

- `/kline/<symbol>` renders with real service-provided OHLC rows.
- `/kline/<symbol>` renders with real service-provided events.
- Empty OHLC and events still render a valid page.
- Backtest API returns metrics, equity curve, and event CAR.
- Backtest API returns chart-ready `signals` once that field is implemented.
- Chart config accepts equity curve and event markers without requiring report
  generation.

Narrative tests:

- Narrative service builds chapter-scoped payloads from `DiseaseReportPackage`.
- Gemini client is mocked; tests do not call the network.
- Chinese language option requests Chinese output.
- English language option requests English output.
- Invalid Gemini JSON falls back to empty narratives.
- IR builder inserts supplied narrative paragraphs.
- IR builder preserves existing table columns and risk fields.
- Narrative generation does not mutate `DiseaseReportPackage`.

## Acceptance Criteria

- K-line visualization and backtest are separate workflows.
- K-line visualization does not require running a report.
- Backtest does not call Gemini.
- Backtest response includes metrics, equity curve, and event CAR.
- Optional signal and trade overlays can be added without changing event storage.
- Disease report Gemini integration is read-only over `DiseaseReportPackage`.
- Gemini output is limited to descriptive chapter strings.
- Gemini does not alter records, risk labels, table fields, or KLine events.
- Chinese and English narrative options are supported.
- If Gemini fails, report generation still succeeds with deterministic text.
- The current single disease report pipeline remains the production report path.
