# Cassandra

Biomedical evidence collection and report generation platform built on Flask + LangGraph.

## Overview

Cassandra focuses on three things:

- structured biomedical source collection (PubMed / ClinicalTrials / Europe PMC / optional FDA)
- deterministic workflow orchestration with explicit state transitions
- final report generation with traceable references and export support

Current online workflow is:

```text
START -> harvester -> extension_handoff -> writer -> END
```

The `extension_handoff` node is a reserved integration point for future agent or rule modules, without breaking the current chain.

## Key Capabilities

- unified harvest output contract with source payload projection
- uninterrupted workflow compilation and execution
- streaming progress updates in the web UI
- markdown + HTML + PDF report output
- extension-ready state field (`extension_payloads`) for future stages

## Quick Start

### 1) Prerequisites

- Python 3.9+
- Google Cloud project with Vertex AI enabled
- `gcloud` CLI configured for ADC

### 2) Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

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
python app.py
```

CLI run:

```bash
python main.py "summarize latest progress on EGFR inhibitors in NSCLC"
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

Harvester output and writer input are validated before report generation.

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
pytest tests
```

Run selected integrity checks:

```bash
python -m pytest tests/test_dataflow_integrity.py
python -m pytest tests/test_report_engine_sanitization.py
```

## Notes

- Existing compatibility adapters under `src/engines/` are kept to reduce migration risk.
- Legacy terms may still appear in historical logs or generated report artifacts; these are not used by the active workflow chain.

## License

See `LICENSE`.
