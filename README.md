# Cassandra

Biomedical evidence collection and report generation platform built on Flask + LangGraph.

## Overview

Cassandra focuses on three things:

- structured biomedical source collection (PubMed / ClinicalTrials / Europe PMC / optional FDA)
- deterministic workflow orchestration with explicit state transitions
- final report generation with traceable references and export support

Current backend workflow is:

```text
START -> harvester -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

Key runtime notes:

- `harvester` emits the normalized record list plus `data_layers`, `source_payloads`, and `frontend_payload`.
- `extension_handoff` initializes extension slots (`slot_a`, `slot_b`, `slot_c`, `slot_kline`).
- the three middle analyzers write their outputs into `extension_payloads`.
- `writer_node` forwards those slots as `synthesis_sections`, but the current `ReportWriterAgent.write_report()` drops `**extra_payload`, so the generic writer still mainly consumes `harvest_data` and `compiled_context_text`.
- disease survey reports are generated from `harvest_data["results"] -> aggregate_survey_data() -> DiseaseSurveyState -> compose_disease_survey_report_bundle()`.

The web UI is intentionally coarser than the backend graph and still shows three stages: `harvest / handoff / writing`.

For a code-level walkthrough, see `docs/competition/architecture/DATA_FLOW_ARCHITECTURE.md`.

## Key Capabilities

- unified harvest output contract with source payload projection
- uninterrupted workflow compilation and execution
- six-node linear backend pipeline with explicit shared state
- markdown + HTML + PDF report output
- disease survey aggregation and rendering pipeline
- extension slot production in the graph for future writer integration

## Quick Start

### 1) Prerequisites

- Python 3.11
- Google Cloud project with Vertex AI enabled
- `gcloud` CLI configured for ADC

### 2) Install

```bash
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pip install -r requirements.txt
```

Use the project Python 3.11 interpreter above. Do not run the app from `F:/miniconda/python.exe`, because that base environment does not include the backtest data dependencies such as `yfinance`.

### 3) Configure

```bash
copy .env.example .env
```

Set at least:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`

Authenticate locally:

```bash
gcloud auth application-default login
```

### 4) Run

Web app:

```bash
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe app.py
```

CLI run:

```bash
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe main.py "summarize latest progress on EGFR inhibitors in NSCLC"
```

## Runtime Architecture

### Workflow Layer

- graph builder: `src/graph/workflow.py`
- shared state: `src/graph/state.py`
- node adapters: `src/graph/nodes/`

### Orchestration Layer

- supervisor entry: `src/agents/supervisor.py`
- service facade: `src/services/workflow_service.py`

### App Layer

- Flask + Socket.IO server: `app.py`
- web templates: `templates/`

## Dataflow Contract

Core schema validation lives in:

- `src/graph/contracts.py`

Harvester output, extension slot payloads, and writer input are validated before report generation.

## Project Layout

```text
Cassandra/
  app.py
  main.py
  config.py
  src/
    agents/
    graph/
    services/
    tools/
    report_engine/
    report_core/
  templates/
  tests/
  docs/
```

## Testing

Run full tests:

```bash
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests
```

Run selected integrity checks:

```bash
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests/test_dataflow_integrity.py
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests/test_writer_slot_consumption.py
C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests/test_report_writer_agent.py
```

## Notes

- Existing compatibility adapters under `src/engines/` are kept to reduce migration risk.
- Legacy terms may still appear in historical logs or generated report artifacts; these are not used by the active workflow chain.
- `extension_payloads` are produced and forwarded today, but full writer-side consumption is still a follow-up integration task.

## License

See `LICENSE`.
