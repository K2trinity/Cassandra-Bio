# Cassandra Extension Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three extension agent nodes (evidence_synthesizer, clinical_analyzer, quality_assessor) to the Cassandra LangGraph pipeline, transforming it from a basic harvest+report system into a high-confidence disease-oriented drug review engine.

**Architecture:** New nodes are inserted between `harvester` and `writer` using LangGraph's explicit node topology (方案 B from the analysis). `evidence_synthesizer` and `clinical_analyzer` run sequentially after `harvester`, then `quality_assessor` consumes both outputs before `writer`. All nodes communicate exclusively through `AgentState` and `extension_payloads` slots.

**Tech Stack:** Python 3.11+, LangGraph StateGraph, Pydantic Settings, loguru, GeminiClient (via `src.llms`)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/engines/evidence_synthesizer/agent.py` | Evidence synthesis engine with GRADE-lite scoring |
| Create | `src/engines/evidence_synthesizer/__init__.py` | Package export |
| Create | `src/engines/clinical_analyzer/agent.py` | Clinical trial pipeline analysis engine |
| Create | `src/engines/clinical_analyzer/__init__.py` | Package export |
| Create | `src/engines/quality_assessor/agent.py` | Data quality & confidence assessment engine |
| Create | `src/engines/quality_assessor/__init__.py` | Package export |
| Create | `src/graph/nodes/evidence_synthesizer_node.py` | LangGraph node wrapper for evidence_synthesizer |
| Create | `src/graph/nodes/clinical_analyzer_node.py` | LangGraph node wrapper for clinical_analyzer |
| Create | `src/graph/nodes/quality_assessor_node.py` | LangGraph node wrapper for quality_assessor |
| Modify | `src/graph/state.py` | Add `slot_c` typing hint in docstring |
| Modify | `src/graph/contracts.py` | Add `EXTENSION_OUTPUT_SCHEMA`, bump contract version |
| Modify | `src/graph/nodes/__init__.py` | Export three new node functions |
| Modify | `src/graph/workflow.py` | New 6-node linear topology |
| Modify | `src/graph/nodes/extension_handoff_node.py` | Add `slot_c` initialization |
| Modify | `src/graph/nodes/writer_node.py` | Consume slot_a/slot_b/slot_c in report payload |
| Modify | `src/agents/supervisor.py` | Update `_initial_state` docstring |
| Modify | `tests/test_dataflow_integrity.py` | Update topology assertions + add extension contract tests |
| Create | `tests/test_evidence_synthesizer.py` | Unit tests for evidence synthesizer |
| Create | `tests/test_clinical_analyzer.py` | Unit tests for clinical analyzer |
| Create | `tests/test_quality_assessor.py` | Unit tests for quality assessor |

---

### Task 1: Bump Contract Version & Add Extension Output Schema

**Files:**
- Modify: `src/graph/contracts.py:15` (version bump)
- Modify: `src/graph/contracts.py:62` (add new schema after WRITER_INPUT_SCHEMA)

- [ ] **Step 1: Write the failing test**

In `tests/test_dataflow_integrity.py`, add after line 109:

```python
@test("Contract version is v4")
def _():
    from src.graph.contracts import CONTRACT_VERSION
    assert CONTRACT_VERSION == "2026-04-17.v4"


@test("Extension output schema exists and validates slot structure")
def _():
    from src.graph.contracts import validate_extension_output

    valid_payload = {
        "slot_id": "slot_a",
        "agent_name": "evidence_synthesizer",
        "data": {"evidence_synthesis": {"layers": []}},
        "status": "success",
    }
    ok, errors = validate_extension_output(valid_payload)
    assert ok, f"Expected valid, got: {errors}"


@test("Extension output rejects missing required fields")
def _():
    from src.graph.contracts import validate_extension_output

    bad_payload = {"slot_id": "slot_a"}
    ok, _ = validate_extension_output(bad_payload)
    assert not ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py`
Expected: FAIL — `CONTRACT_VERSION == "2026-04-14.v3"` and `validate_extension_output` not found.

- [ ] **Step 3: Update contract version and add schema**

In `src/graph/contracts.py`, change line 15:

```python
CONTRACT_VERSION = "2026-04-17.v4"
```

After `WRITER_INPUT_SCHEMA` (after line 61), add:

```python
EXTENSION_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "cassandra://contracts/extension-output",
    "title": "Extension Agent Output Contract",
    "type": "object",
    "required": ["slot_id", "agent_name", "data", "status"],
    "properties": {
        "slot_id": {"type": "string"},
        "agent_name": {"type": "string"},
        "data": {"type": "object"},
        "status": {"type": "string"},
    },
    "additionalProperties": True,
}
```

At the bottom of the file, add:

```python
def validate_extension_output(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = validate_payload(payload, EXTENSION_OUTPUT_SCHEMA)
    return len(errors) == 0, errors
```

- [ ] **Step 4: Fix the old contract version test**

In `tests/test_dataflow_integrity.py`, replace the existing `"Contract version is v3"` test (line 56-60) by changing `v3` to `v4`:

```python
@test("Contract version is v4")
def _():
    from src.graph.contracts import CONTRACT_VERSION
    assert CONTRACT_VERSION == "2026-04-17.v4"
```

Then remove the duplicate `"Contract version is v4"` test that was added in Step 1 — only one copy should remain.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/contracts.py tests/test_dataflow_integrity.py
git commit -m "feat(contracts): bump to v4, add EXTENSION_OUTPUT_SCHEMA"
```

---

### Task 2: Extend AgentState & Extension Handoff for slot_c

**Files:**
- Modify: `src/graph/state.py:65` (docstring update)
- Modify: `src/graph/nodes/extension_handoff_node.py:35-36` (add slot_c)

- [ ] **Step 1: Write the failing test**

Create `tests/test_extension_handoff.py`:

```python
"""Unit tests for extension_handoff_node slot initialization."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.graph.nodes.extension_handoff_node import extension_handoff_node


def test_handoff_initializes_three_slots():
    state = {"extension_payloads": None}
    result = extension_handoff_node(state)
    payloads = result["extension_payloads"]
    assert "slot_a" in payloads
    assert "slot_b" in payloads
    assert "slot_c" in payloads
    assert payloads["slot_a"] == {}
    assert payloads["slot_b"] == {}
    assert payloads["slot_c"] == {}


def test_handoff_preserves_existing_slot_data():
    state = {
        "extension_payloads": {
            "slot_a": {"evidence_synthesis": {"layers": [1, 2]}},
        }
    }
    result = extension_handoff_node(state)
    payloads = result["extension_payloads"]
    assert payloads["slot_a"] == {"evidence_synthesis": {"layers": [1, 2]}}
    assert payloads["slot_b"] == {}
    assert payloads["slot_c"] == {}


if __name__ == "__main__":
    test_handoff_initializes_three_slots()
    print("[PASS] test_handoff_initializes_three_slots")
    test_handoff_preserves_existing_slot_data()
    print("[PASS] test_handoff_preserves_existing_slot_data")
    print("All extension handoff tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_extension_handoff.py`
Expected: FAIL — `assert "slot_c" in payloads` fails.

- [ ] **Step 3: Add slot_c to extension_handoff_node**

In `src/graph/nodes/extension_handoff_node.py`, after line 36 (`extension_payloads.setdefault("slot_b", {})`), add:

```python
    extension_payloads.setdefault("slot_c", {})
```

- [ ] **Step 4: Update AgentState docstring**

In `src/graph/state.py`, update the docstring (line 33) to reflect the new slot:

```python
        3. Extension handoff prepares agent slots (slot_a, slot_b, slot_c)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_extension_handoff.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/extension_handoff_node.py src/graph/state.py tests/test_extension_handoff.py
git commit -m "feat(handoff): add slot_c for quality_assessor"
```

---

### Task 3: Evidence Synthesizer Engine

**Files:**
- Create: `src/engines/evidence_synthesizer/__init__.py`
- Create: `src/engines/evidence_synthesizer/agent.py`
- Create: `tests/test_evidence_synthesizer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evidence_synthesizer.py`:

```python
"""Unit tests for EvidenceSynthesizerAgent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engines.evidence_synthesizer.agent import EvidenceSynthesizerAgent


def test_classify_evidence_level_meta_analysis():
    agent = EvidenceSynthesizerAgent()
    record = {
        "title": "A meta-analysis of drug X efficacy",
        "source": "PubMed",
        "metadata": {},
    }
    level = agent._classify_evidence_level(record)
    assert level == "meta_analysis"


def test_classify_evidence_level_rct():
    agent = EvidenceSynthesizerAgent()
    record = {
        "title": "Randomized controlled trial of drug Y",
        "source": "PubMed",
        "metadata": {"phase": "Phase III"},
    }
    level = agent._classify_evidence_level(record)
    assert level == "rct"


def test_classify_evidence_level_clinical_trial():
    agent = EvidenceSynthesizerAgent()
    record = {
        "title": "Phase II study of drug Z",
        "source": "ClinicalTrials.gov",
        "nct_id": "NCT12345678",
        "metadata": {},
    }
    level = agent._classify_evidence_level(record)
    assert level == "clinical_trial"


def test_classify_evidence_level_case_report():
    agent = EvidenceSynthesizerAgent()
    record = {
        "title": "A case report of adverse reaction",
        "source": "PubMed",
        "metadata": {},
    }
    level = agent._classify_evidence_level(record)
    assert level == "case_report"


def test_classify_evidence_level_other():
    agent = EvidenceSynthesizerAgent()
    record = {"title": "General review of treatments", "source": "PubMed", "metadata": {}}
    level = agent._classify_evidence_level(record)
    assert level == "other"


def test_extract_efficacy_endpoints():
    agent = EvidenceSynthesizerAgent()
    text = "Overall survival (OS) was 12.5 months. Progression-free survival PFS 6.2 months. ORR was 45%."
    endpoints = agent._extract_efficacy_endpoints(text)
    assert "OS" in endpoints or "overall_survival" in [e.get("type") for e in endpoints]


def test_synthesize_returns_valid_structure():
    agent = EvidenceSynthesizerAgent()
    harvested_data = [
        {
            "title": "Meta-analysis of drug X in lung cancer",
            "summary": "OS was 14.2 months. ORR 38%. PFS 7.1 months.",
            "source": "PubMed",
            "pmid": "12345678",
            "metadata": {},
        },
        {
            "title": "Phase III RCT of drug X",
            "summary": "Randomized controlled trial showed CR in 12% of patients.",
            "source": "PubMed",
            "pmid": "87654321",
            "metadata": {"phase": "Phase III"},
        },
    ]
    data_layers = {}
    result = agent.synthesize(harvested_data, data_layers)

    assert "evidence_layers" in result
    assert "efficacy_endpoints" in result
    assert "conflicts" in result
    assert "grade_scores" in result
    assert isinstance(result["evidence_layers"], dict)
    assert isinstance(result["efficacy_endpoints"], list)
    assert isinstance(result["conflicts"], list)
    assert isinstance(result["grade_scores"], dict)


def test_synthesize_empty_input():
    agent = EvidenceSynthesizerAgent()
    result = agent.synthesize([], {})
    assert result["evidence_layers"] == {}
    assert result["efficacy_endpoints"] == []
    assert result["conflicts"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
    print("Evidence synthesizer tests complete.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_evidence_synthesizer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.evidence_synthesizer'`

- [ ] **Step 3: Create the engine package**

Create `src/engines/evidence_synthesizer/__init__.py`:

```python
"""Evidence Synthesizer engine for GRADE-lite evidence layering."""

from .agent import EvidenceSynthesizerAgent, create_evidence_synthesizer

__all__ = ["EvidenceSynthesizerAgent", "create_evidence_synthesizer"]
```

- [ ] **Step 4: Implement EvidenceSynthesizerAgent**

Create `src/engines/evidence_synthesizer/agent.py`:

```python
"""Evidence Synthesizer Agent — GRADE-lite evidence layering and endpoint extraction.

Classifies harvested records by evidence level, extracts efficacy endpoints,
identifies conflicting evidence, and produces a simplified GRADE strength score.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Dict, List, Optional


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

EVIDENCE_HIERARCHY = ["meta_analysis", "rct", "clinical_trial", "cohort", "case_report", "other"]

GRADE_WEIGHTS = {
    "meta_analysis": 5,
    "rct": 4,
    "clinical_trial": 3,
    "cohort": 2,
    "case_report": 1,
    "other": 0,
}


class EvidenceSynthesizerAgent:
    """Synthesize harvested biomedical records into layered evidence."""

    def synthesize(
        self,
        harvested_data: List[Dict[str, Any]],
        data_layers: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "evidence_layers": {},
                "efficacy_endpoints": [],
                "conflicts": [],
                "grade_scores": {},
            }

        evidence_layers: Dict[str, List[Dict[str, Any]]] = {}
        all_endpoints: List[Dict[str, Any]] = []

        for record in harvested_data:
            if not isinstance(record, dict):
                continue
            level = self._classify_evidence_level(record)
            evidence_layers.setdefault(level, []).append({
                "title": str(record.get("title") or ""),
                "pmid": str(record.get("pmid") or ""),
                "nct_id": str(record.get("nct_id") or ""),
                "source": str(record.get("source") or ""),
            })

            text = " ".join([
                str(record.get("summary") or ""),
                str(record.get("abstract") or ""),
                str(record.get("title") or ""),
            ])
            endpoints = self._extract_efficacy_endpoints(text)
            for ep in endpoints:
                ep["source_title"] = str(record.get("title") or "")
                ep["evidence_level"] = level
            all_endpoints.extend(endpoints)

        conflicts = self._detect_conflicts(all_endpoints)
        grade_scores = self._compute_grade_scores(evidence_layers)

        return {
            "evidence_layers": {k: v for k, v in evidence_layers.items()},
            "efficacy_endpoints": all_endpoints,
            "conflicts": conflicts,
            "grade_scores": grade_scores,
        }

    def _classify_evidence_level(self, record: Dict[str, Any]) -> str:
        title = str(record.get("title") or "").lower()
        summary = str(record.get("summary") or record.get("abstract") or "").lower()
        source = str(record.get("source") or "").lower()
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        phase = str(metadata.get("phase") or "").lower()
        nct_id = record.get("nct_id") or ""
        combined = f"{title} {summary}"

        if re.search(r"meta[\s-]?analysis|systematic review", combined):
            return "meta_analysis"
        if re.search(r"randomized controlled|randomised controlled|\brct\b", combined) or "phase iii" in phase:
            return "rct"
        if nct_id or "clinicaltrials" in source or re.search(r"phase [i|ii|iv]", combined):
            return "clinical_trial"
        if re.search(r"cohort|observational|retrospective|prospective study", combined):
            return "cohort"
        if re.search(r"case report|case series|single.?patient", combined):
            return "case_report"
        return "other"

    def _extract_efficacy_endpoints(self, text: str) -> List[Dict[str, Any]]:
        endpoints: List[Dict[str, Any]] = []
        patterns = [
            (r"overall\s+survival\s*\(?OS\)?\s*(?:was|of|:)?\s*([\d.]+)\s*(months?|years?)?", "overall_survival"),
            (r"(?:progression[- ]free\s+survival|PFS)\s*(?:was|of|:)?\s*([\d.]+)\s*(months?|years?)?", "pfs"),
            (r"(?:overall\s+response\s+rate|ORR)\s*(?:was|of|:)?\s*([\d.]+)\s*%?", "orr"),
            (r"(?:complete\s+response|CR)\s*(?:was|of|:)?\s*(?:in\s+)?([\d.]+)\s*%?", "cr"),
            (r"(?:partial\s+response|PR)\s*(?:was|of|:)?\s*(?:in\s+)?([\d.]+)\s*%?", "pr"),
        ]
        for pattern, ep_type in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group(1)
                unit = match.group(2) if match.lastindex >= 2 else None
                endpoints.append({
                    "type": ep_type,
                    "value": float(value),
                    "unit": str(unit or "").strip() or None,
                    "raw_match": match.group(0).strip(),
                })
        return endpoints

    def _detect_conflicts(self, endpoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for ep in endpoints:
            by_type.setdefault(ep["type"], []).append(ep)

        conflicts: List[Dict[str, Any]] = []
        for ep_type, items in by_type.items():
            if len(items) < 2:
                continue
            values = [it["value"] for it in items]
            min_val, max_val = min(values), max(values)
            if max_val > 0 and (max_val - min_val) / max_val > 0.5:
                conflicts.append({
                    "endpoint_type": ep_type,
                    "min_value": min_val,
                    "max_value": max_val,
                    "spread_ratio": round((max_val - min_val) / max_val, 2),
                    "sources": [it.get("source_title", "") for it in items],
                })
        return conflicts

    def _compute_grade_scores(self, evidence_layers: Dict[str, List]) -> Dict[str, Any]:
        total_weight = 0
        total_records = 0
        per_level: Dict[str, int] = {}
        for level, records in evidence_layers.items():
            count = len(records)
            per_level[level] = count
            total_records += count
            total_weight += count * GRADE_WEIGHTS.get(level, 0)

        if total_records == 0:
            return {"overall": "D", "score": 0, "breakdown": {}}

        avg_weight = total_weight / total_records
        if avg_weight >= 4.0:
            grade = "A"
        elif avg_weight >= 3.0:
            grade = "B"
        elif avg_weight >= 2.0:
            grade = "C"
        else:
            grade = "D"

        return {
            "overall": grade,
            "score": round(avg_weight, 2),
            "breakdown": per_level,
        }


def create_evidence_synthesizer() -> EvidenceSynthesizerAgent:
    return EvidenceSynthesizerAgent()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_evidence_synthesizer.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/engines/evidence_synthesizer/ tests/test_evidence_synthesizer.py
git commit -m "feat(engines): add evidence_synthesizer with GRADE-lite scoring"
```

---

### Task 4: Evidence Synthesizer Node

**Files:**
- Create: `src/graph/nodes/evidence_synthesizer_node.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_evidence_synthesizer.py`:

```python
def test_evidence_synthesizer_node_writes_slot_a():
    from src.graph.nodes.evidence_synthesizer_node import evidence_synthesizer_node

    state = {
        "harvested_data": [
            {
                "title": "Meta-analysis of drug X",
                "summary": "OS was 14.2 months.",
                "source": "PubMed",
                "pmid": "111",
                "metadata": {},
            },
        ],
        "harvest_data_layers": {},
        "extension_payloads": {"slot_a": {}, "slot_b": {}, "slot_c": {}},
    }
    result = evidence_synthesizer_node(state)
    assert result["status"] == "evidence_synthesis_complete"
    slot_a = result["extension_payloads"]["slot_a"]
    assert "evidence_synthesis" in slot_a
    assert "evidence_layers" in slot_a["evidence_synthesis"]


def test_evidence_synthesizer_node_handles_empty_data():
    from src.graph.nodes.evidence_synthesizer_node import evidence_synthesizer_node

    state = {
        "harvested_data": [],
        "harvest_data_layers": {},
        "extension_payloads": {"slot_a": {}, "slot_b": {}, "slot_c": {}},
    }
    result = evidence_synthesizer_node(state)
    assert result["status"] == "evidence_synthesis_complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_evidence_synthesizer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.graph.nodes.evidence_synthesizer_node'`

- [ ] **Step 3: Implement the node**

Create `src/graph/nodes/evidence_synthesizer_node.py`:

```python
"""Evidence Synthesizer workflow node."""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.evidence_synthesizer.agent import create_evidence_synthesizer
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def evidence_synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """Classify evidence layers and extract efficacy endpoints."""
    logger.info("🔬 NODE: EVIDENCE SYNTHESIZER")

    try:
        agent = create_evidence_synthesizer()
        harvested_data = state.get("harvested_data", []) or []
        data_layers = state.get("harvest_data_layers", {}) or {}

        synthesis = agent.synthesize(harvested_data, data_layers)

        extension_payloads = dict(state.get("extension_payloads", {}) or {})
        slot_payload = {
            "slot_id": "slot_a",
            "agent_name": "evidence_synthesizer",
            "data": {"evidence_synthesis": synthesis},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Evidence synthesizer output contract failed: {errors[:5]}")

        extension_payloads["slot_a"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "evidence_synthesis_complete",
        }
    except Exception as exc:
        logger.error(f"Evidence synthesizer failed: {exc}")
        return {
            "errors": [f"EvidenceSynthesizer: {str(exc)}"],
            "status": "evidence_synthesis_failed",
        }


__all__ = ["evidence_synthesizer_node"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_evidence_synthesizer.py`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/evidence_synthesizer_node.py tests/test_evidence_synthesizer.py
git commit -m "feat(nodes): add evidence_synthesizer_node writing to slot_a"
```

---

### Task 5: Clinical Analyzer Engine

**Files:**
- Create: `src/engines/clinical_analyzer/__init__.py`
- Create: `src/engines/clinical_analyzer/agent.py`
- Create: `tests/test_clinical_analyzer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_clinical_analyzer.py`:

```python
"""Unit tests for ClinicalAnalyzerAgent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engines.clinical_analyzer.agent import ClinicalAnalyzerAgent


def test_build_pipeline_matrix_groups_by_phase():
    agent = ClinicalAnalyzerAgent()
    records = [
        {"title": "Drug A Phase I", "nct_id": "NCT001", "metadata": {"phase": "Phase I", "conditions": ["Lung Cancer"], "interventions": ["Drug A"], "status": "Completed"}},
        {"title": "Drug A Phase II", "nct_id": "NCT002", "metadata": {"phase": "Phase II", "conditions": ["Lung Cancer"], "interventions": ["Drug A"], "status": "Recruiting"}},
        {"title": "Drug A Phase III", "nct_id": "NCT003", "metadata": {"phase": "Phase III", "conditions": ["Lung Cancer"], "interventions": ["Drug A"], "status": "Completed"}},
    ]
    matrix = agent._build_pipeline_matrix(records)
    assert isinstance(matrix, list)
    assert len(matrix) >= 1
    entry = matrix[0]
    assert "indication" in entry
    assert "intervention" in entry
    assert "phases" in entry


def test_compute_phase_transitions():
    agent = ClinicalAnalyzerAgent()
    records = [
        {"nct_id": "NCT001", "metadata": {"phase": "Phase I", "status": "Completed"}},
        {"nct_id": "NCT002", "metadata": {"phase": "Phase II", "status": "Completed"}},
        {"nct_id": "NCT003", "metadata": {"phase": "Phase III", "status": "Recruiting"}},
        {"nct_id": "NCT004", "metadata": {"phase": "Phase I", "status": "Terminated"}},
    ]
    transitions = agent._compute_phase_transitions(records)
    assert isinstance(transitions, dict)
    assert "phase_counts" in transitions


def test_extract_safety_signals():
    agent = ClinicalAnalyzerAgent()
    records = [
        {"title": "Study with SAE", "summary": "Serious adverse events reported in 15% of patients. Black box warning issued.", "metadata": {}},
        {"title": "Safe study", "summary": "Well tolerated with mild side effects.", "metadata": {}},
    ]
    signals = agent._extract_safety_signals(records)
    assert isinstance(signals, list)
    assert len(signals) >= 1
    assert signals[0]["title"] == "Study with SAE"


def test_analyze_returns_valid_structure():
    agent = ClinicalAnalyzerAgent()
    harvested_data = [
        {"title": "Phase III RCT", "nct_id": "NCT001", "source": "ClinicalTrials.gov", "summary": "Completed trial.", "metadata": {"phase": "Phase III", "conditions": ["NSCLC"], "interventions": ["Pembrolizumab"], "status": "Completed"}},
    ]
    source_payloads = {}
    result = agent.analyze(harvested_data, source_payloads)
    assert "pipeline_matrix" in result
    assert "phase_transitions" in result
    assert "safety_signals" in result
    assert "competition_landscape" in result


def test_analyze_empty_input():
    agent = ClinicalAnalyzerAgent()
    result = agent.analyze([], {})
    assert result["pipeline_matrix"] == []
    assert result["safety_signals"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                import traceback; traceback.print_exc()
    print("Clinical analyzer tests complete.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_clinical_analyzer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.clinical_analyzer'`

- [ ] **Step 3: Create the engine package**

Create `src/engines/clinical_analyzer/__init__.py`:

```python
"""Clinical Analyzer engine for pipeline matrix and safety signal extraction."""

from .agent import ClinicalAnalyzerAgent, create_clinical_analyzer

__all__ = ["ClinicalAnalyzerAgent", "create_clinical_analyzer"]
```

- [ ] **Step 4: Implement ClinicalAnalyzerAgent**

Create `src/engines/clinical_analyzer/agent.py`:

```python
"""Clinical Analyzer Agent — pipeline matrix, phase transitions, safety signals.

Parses clinical trial records to build an indication x drug x phase matrix,
computes phase transition rates, extracts safety signals, and maps competition.
"""

from __future__ import annotations

import importlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

PHASE_ORDER = ["Phase I", "Phase I/II", "Phase II", "Phase II/III", "Phase III", "Phase IV", "Approved"]

SAFETY_PATTERNS = [
    (r"serious adverse|severe adverse|\bSAE\b", "serious_adverse_event"),
    (r"black.?box warning", "black_box_warning"),
    (r"terminated|withdrawn", "trial_terminated"),
    (r"discontinu(?:ed|ation)\s+(?:due to|because of)\s+(?:adverse|safety|toxicity)", "discontinuation_safety"),
    (r"death|fatal(?:ity)?|mortality", "mortality_signal"),
    (r"dose.?limiting toxicit", "dose_limiting_toxicity"),
]


class ClinicalAnalyzerAgent:
    """Analyze clinical trial data for pipeline and safety insights."""

    def analyze(
        self,
        harvested_data: List[Dict[str, Any]],
        source_payloads: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "pipeline_matrix": [],
                "phase_transitions": {"phase_counts": {}, "total_trials": 0},
                "safety_signals": [],
                "competition_landscape": {},
            }

        trial_records = [
            r for r in harvested_data
            if isinstance(r, dict) and (
                r.get("nct_id")
                or (isinstance(r.get("metadata"), dict) and r["metadata"].get("nct_id"))
                or r.get("source") == "ClinicalTrials.gov"
            )
        ]

        pipeline_matrix = self._build_pipeline_matrix(trial_records)
        phase_transitions = self._compute_phase_transitions(trial_records)
        safety_signals = self._extract_safety_signals(harvested_data)
        competition = self._map_competition(trial_records)

        return {
            "pipeline_matrix": pipeline_matrix,
            "phase_transitions": phase_transitions,
            "safety_signals": safety_signals,
            "competition_landscape": competition,
        }

    def _build_pipeline_matrix(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        combos: Dict[str, Dict[str, Any]] = {}

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            phase = str(meta.get("phase") or "Unknown")
            status = str(meta.get("status") or "Unknown")
            nct_id = str(rec.get("nct_id") or meta.get("nct_id") or "")

            indications = meta.get("conditions") or []
            if isinstance(indications, str):
                indications = [indications]
            if not indications:
                indications = ["Unknown"]

            interventions = meta.get("interventions") or []
            if isinstance(interventions, str):
                interventions = [interventions]
            if not interventions:
                interventions = ["Unknown"]

            for indication in indications:
                for intervention in interventions:
                    key = f"{indication}||{intervention}"
                    if key not in combos:
                        combos[key] = {
                            "indication": str(indication),
                            "intervention": str(intervention),
                            "phases": {},
                            "trial_count": 0,
                        }
                    entry = combos[key]
                    entry["trial_count"] += 1
                    phase_entry = entry["phases"].setdefault(phase, [])
                    phase_entry.append({"nct_id": nct_id, "status": status})

        return sorted(combos.values(), key=lambda x: x["trial_count"], reverse=True)

    def _compute_phase_transitions(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        phase_counts: Dict[str, int] = defaultdict(int)
        status_by_phase: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            phase = str(meta.get("phase") or "Unknown")
            status = str(meta.get("status") or "Unknown")
            phase_counts[phase] += 1
            status_by_phase[phase][status] += 1

        return {
            "phase_counts": dict(phase_counts),
            "status_by_phase": {k: dict(v) for k, v in status_by_phase.items()},
            "total_trials": sum(phase_counts.values()),
        }

    def _extract_safety_signals(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []

        for rec in records:
            if not isinstance(rec, dict):
                continue
            text = " ".join([
                str(rec.get("title") or ""),
                str(rec.get("summary") or rec.get("abstract") or ""),
            ])
            matched_types: List[str] = []
            for pattern, signal_type in SAFETY_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    matched_types.append(signal_type)

            if matched_types:
                signals.append({
                    "title": str(rec.get("title") or ""),
                    "nct_id": str(rec.get("nct_id") or ""),
                    "pmid": str(rec.get("pmid") or ""),
                    "signal_types": matched_types,
                })

        return signals

    def _map_competition(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_target: Dict[str, Set[str]] = defaultdict(set)
        by_indication: Dict[str, Set[str]] = defaultdict(set)

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            interventions = meta.get("interventions") or []
            if isinstance(interventions, str):
                interventions = [interventions]
            conditions = meta.get("conditions") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            targets = meta.get("targets") or []
            if isinstance(targets, str):
                targets = [targets]

            for target in targets:
                for intervention in interventions:
                    by_target[str(target)].add(str(intervention))
            for condition in conditions:
                for intervention in interventions:
                    by_indication[str(condition)].add(str(intervention))

        return {
            "by_target": {k: sorted(v) for k, v in by_target.items()},
            "by_indication": {k: sorted(v) for k, v in by_indication.items()},
        }


def create_clinical_analyzer() -> ClinicalAnalyzerAgent:
    return ClinicalAnalyzerAgent()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_clinical_analyzer.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/engines/clinical_analyzer/ tests/test_clinical_analyzer.py
git commit -m "feat(engines): add clinical_analyzer with pipeline matrix and safety signals"
```

---

### Task 6: Clinical Analyzer Node

**Files:**
- Create: `src/graph/nodes/clinical_analyzer_node.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_clinical_analyzer.py`:

```python
def test_clinical_analyzer_node_writes_slot_b():
    from src.graph.nodes.clinical_analyzer_node import clinical_analyzer_node

    state = {
        "harvested_data": [
            {"title": "Phase III trial", "nct_id": "NCT001", "source": "ClinicalTrials.gov", "summary": "Completed.", "metadata": {"phase": "Phase III", "conditions": ["NSCLC"], "interventions": ["Drug A"], "status": "Completed"}},
        ],
        "harvest_source_payloads": {},
        "extension_payloads": {"slot_a": {"evidence_synthesis": {}}, "slot_b": {}, "slot_c": {}},
    }
    result = clinical_analyzer_node(state)
    assert result["status"] == "clinical_analysis_complete"
    slot_b = result["extension_payloads"]["slot_b"]
    assert "clinical_analysis" in slot_b
    assert "pipeline_matrix" in slot_b["clinical_analysis"]


def test_clinical_analyzer_node_handles_empty():
    from src.graph.nodes.clinical_analyzer_node import clinical_analyzer_node

    state = {
        "harvested_data": [],
        "harvest_source_payloads": {},
        "extension_payloads": {"slot_a": {}, "slot_b": {}, "slot_c": {}},
    }
    result = clinical_analyzer_node(state)
    assert result["status"] == "clinical_analysis_complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_clinical_analyzer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.graph.nodes.clinical_analyzer_node'`

- [ ] **Step 3: Implement the node**

Create `src/graph/nodes/clinical_analyzer_node.py`:

```python
"""Clinical Analyzer workflow node."""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.clinical_analyzer.agent import create_clinical_analyzer
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def clinical_analyzer_node(state: AgentState) -> Dict[str, Any]:
    """Build pipeline matrix and extract safety signals from clinical data."""
    logger.info("🧪 NODE: CLINICAL ANALYZER")

    try:
        agent = create_clinical_analyzer()
        harvested_data = state.get("harvested_data", []) or []
        source_payloads = state.get("harvest_source_payloads", {}) or {}

        analysis = agent.analyze(harvested_data, source_payloads)

        extension_payloads = dict(state.get("extension_payloads", {}) or {})
        slot_payload = {
            "slot_id": "slot_b",
            "agent_name": "clinical_analyzer",
            "data": {"clinical_analysis": analysis},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Clinical analyzer output contract failed: {errors[:5]}")

        extension_payloads["slot_b"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "clinical_analysis_complete",
        }
    except Exception as exc:
        logger.error(f"Clinical analyzer failed: {exc}")
        return {
            "errors": [f"ClinicalAnalyzer: {str(exc)}"],
            "status": "clinical_analysis_failed",
        }


__all__ = ["clinical_analyzer_node"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_clinical_analyzer.py`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/clinical_analyzer_node.py tests/test_clinical_analyzer.py
git commit -m "feat(nodes): add clinical_analyzer_node writing to slot_b"
```

---

### Task 7: Quality Assessor Engine

**Files:**
- Create: `src/engines/quality_assessor/__init__.py`
- Create: `src/engines/quality_assessor/agent.py`
- Create: `tests/test_quality_assessor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_quality_assessor.py`:

```python
"""Unit tests for QualityAssessorAgent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engines.quality_assessor.agent import QualityAssessorAgent


def test_check_completeness():
    agent = QualityAssessorAgent()
    records = [
        {"title": "Study A", "pmid": "111", "source": "PubMed", "summary": "Results.", "metadata": {"phase": "Phase III"}},
        {"title": "Study B", "source": "PubMed", "summary": "More results.", "metadata": {}},
    ]
    result = agent._check_completeness(records)
    assert "field_coverage" in result
    assert "title" in result["field_coverage"]
    assert result["field_coverage"]["title"] == 1.0


def test_score_source_diversity_multi_source():
    agent = QualityAssessorAgent()
    records = [
        {"source": "PubMed"},
        {"source": "ClinicalTrials.gov"},
        {"source": "EuroPMC"},
    ]
    score = agent._score_source_diversity(records)
    assert score > 0.5


def test_score_source_diversity_single_source():
    agent = QualityAssessorAgent()
    records = [{"source": "PubMed"}, {"source": "PubMed"}]
    score = agent._score_source_diversity(records)
    assert score <= 0.5


def test_assess_timeliness():
    agent = QualityAssessorAgent()
    records = [
        {"metadata": {"year": "2025"}},
        {"metadata": {"year": "2024"}},
        {"metadata": {"year": "2018"}},
    ]
    result = agent._assess_timeliness(records)
    assert "year_distribution" in result
    assert "recency_score" in result


def test_compute_confidence_grade():
    agent = QualityAssessorAgent()
    assert agent._compute_confidence_grade(0.9) == "A"
    assert agent._compute_confidence_grade(0.7) == "B"
    assert agent._compute_confidence_grade(0.5) == "C"
    assert agent._compute_confidence_grade(0.2) == "D"


def test_assess_returns_valid_structure():
    agent = QualityAssessorAgent()
    harvested_data = [
        {"title": "Study", "pmid": "1", "source": "PubMed", "summary": "Text", "metadata": {"year": "2025"}},
    ]
    slot_a = {"evidence_synthesis": {"grade_scores": {"overall": "B", "score": 3.5}}}
    slot_b = {"clinical_analysis": {"pipeline_matrix": [], "safety_signals": []}}
    result = agent.assess(harvested_data, slot_a, slot_b)
    assert "completeness" in result
    assert "source_diversity_score" in result
    assert "timeliness" in result
    assert "confidence_grade" in result
    assert result["confidence_grade"] in ("A", "B", "C", "D")


def test_assess_empty_input():
    agent = QualityAssessorAgent()
    result = agent.assess([], {}, {})
    assert result["confidence_grade"] == "D"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                import traceback; traceback.print_exc()
    print("Quality assessor tests complete.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_quality_assessor.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.quality_assessor'`

- [ ] **Step 3: Create the engine package**

Create `src/engines/quality_assessor/__init__.py`:

```python
"""Quality Assessor engine for data completeness and confidence grading."""

from .agent import QualityAssessorAgent, create_quality_assessor

__all__ = ["QualityAssessorAgent", "create_quality_assessor"]
```

- [ ] **Step 4: Implement QualityAssessorAgent**

Create `src/engines/quality_assessor/agent.py`:

```python
"""Quality Assessor Agent — data completeness, source diversity, timeliness, confidence.

Performs an independent quality audit of harvested data and upstream extension
slot outputs, producing a final confidence grade (A/B/C/D) with rationale.
"""

from __future__ import annotations

import importlib
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

REQUIRED_FIELDS = ["title", "source", "summary", "pmid"]
CURRENT_YEAR = datetime.now().year


class QualityAssessorAgent:
    """Assess data quality and produce a confidence grade."""

    def assess(
        self,
        harvested_data: List[Dict[str, Any]],
        slot_a_data: Dict[str, Any],
        slot_b_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "completeness": {"field_coverage": {}, "overall_completeness": 0.0},
                "source_diversity_score": 0.0,
                "timeliness": {"year_distribution": {}, "recency_score": 0.0},
                "bias_indicators": [],
                "confidence_grade": "D",
                "confidence_score": 0.0,
                "rationale": "No data available for assessment.",
            }

        completeness = self._check_completeness(harvested_data)
        diversity = self._score_source_diversity(harvested_data)
        timeliness = self._assess_timeliness(harvested_data)
        bias = self._detect_bias_indicators(harvested_data)

        evidence_grade_score = 0.0
        evidence_synthesis = slot_a_data.get("evidence_synthesis", {})
        if isinstance(evidence_synthesis, dict):
            grade_scores = evidence_synthesis.get("grade_scores", {})
            if isinstance(grade_scores, dict):
                evidence_grade_score = float(grade_scores.get("score", 0))

        composite = (
            completeness["overall_completeness"] * 0.25
            + diversity * 0.25
            + timeliness["recency_score"] * 0.25
            + min(evidence_grade_score / 5.0, 1.0) * 0.25
        )
        confidence_score = round(composite, 3)
        grade = self._compute_confidence_grade(confidence_score)

        rationale_parts = []
        if completeness["overall_completeness"] < 0.5:
            rationale_parts.append("Low field completeness in harvested records.")
        if diversity < 0.4:
            rationale_parts.append("Limited source diversity — mostly single-source data.")
        if timeliness["recency_score"] < 0.4:
            rationale_parts.append("Data skews toward older publications.")
        if bias:
            rationale_parts.append(f"{len(bias)} potential bias indicator(s) detected.")
        if not rationale_parts:
            rationale_parts.append("Data quality metrics are within acceptable ranges.")

        return {
            "completeness": completeness,
            "source_diversity_score": round(diversity, 3),
            "timeliness": timeliness,
            "bias_indicators": bias,
            "confidence_grade": grade,
            "confidence_score": confidence_score,
            "rationale": " ".join(rationale_parts),
        }

    def _check_completeness(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not records:
            return {"field_coverage": {}, "overall_completeness": 0.0}

        total = len(records)
        field_counts: Dict[str, int] = {f: 0 for f in REQUIRED_FIELDS}

        for rec in records:
            if not isinstance(rec, dict):
                continue
            for field in REQUIRED_FIELDS:
                val = rec.get(field)
                if val and str(val).strip():
                    field_counts[field] += 1

        coverage = {f: round(c / total, 3) for f, c in field_counts.items()}
        overall = round(sum(coverage.values()) / len(coverage), 3) if coverage else 0.0

        return {"field_coverage": coverage, "overall_completeness": overall}

    def _score_source_diversity(self, records: List[Dict[str, Any]]) -> float:
        sources = [str(r.get("source") or "unknown") for r in records if isinstance(r, dict)]
        if not sources:
            return 0.0

        unique = len(set(sources))
        total = len(sources)
        counter = Counter(sources)
        max_share = max(counter.values()) / total if total else 1.0

        diversity = min(1.0, (unique / 5.0) * 0.5 + (1.0 - max_share) * 0.5)
        return round(diversity, 3)

    def _assess_timeliness(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        years: List[int] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            year_str = str(meta.get("year") or rec.get("year") or rec.get("publication_year") or "")
            match = re.search(r"(19|20)\d{2}", year_str)
            if match:
                years.append(int(match.group(0)))

        if not years:
            return {"year_distribution": {}, "recency_score": 0.0}

        dist = dict(Counter(years))
        recent_count = sum(1 for y in years if y >= CURRENT_YEAR - 3)
        recency_score = round(recent_count / len(years), 3)

        return {"year_distribution": dist, "recency_score": recency_score}

    def _detect_bias_indicators(self, records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        indicators: List[Dict[str, str]] = []
        sources = [str(r.get("source") or "") for r in records if isinstance(r, dict)]
        counter = Counter(sources)
        total = len(sources)

        if total > 0:
            for src, count in counter.items():
                if count / total > 0.8 and total >= 5:
                    indicators.append({
                        "type": "source_concentration",
                        "detail": f"{src} accounts for {count}/{total} records ({round(count/total*100)}%)",
                    })

        sponsor_pattern = re.compile(r"funded by|sponsored by|grant from", re.IGNORECASE)
        sponsored_count = 0
        for rec in records:
            if not isinstance(rec, dict):
                continue
            text = str(rec.get("summary") or rec.get("abstract") or "")
            if sponsor_pattern.search(text):
                sponsored_count += 1
        if sponsored_count > 0 and total > 0 and sponsored_count / total > 0.5:
            indicators.append({
                "type": "funding_bias",
                "detail": f"{sponsored_count}/{total} records mention explicit funding/sponsorship",
            })

        return indicators

    def _compute_confidence_grade(self, score: float) -> str:
        if score >= 0.8:
            return "A"
        if score >= 0.6:
            return "B"
        if score >= 0.4:
            return "C"
        return "D"


def create_quality_assessor() -> QualityAssessorAgent:
    return QualityAssessorAgent()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_quality_assessor.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/engines/quality_assessor/ tests/test_quality_assessor.py
git commit -m "feat(engines): add quality_assessor with confidence grading"
```

---

### Task 8: Quality Assessor Node

**Files:**
- Create: `src/graph/nodes/quality_assessor_node.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quality_assessor.py`:

```python
def test_quality_assessor_node_writes_slot_c():
    from src.graph.nodes.quality_assessor_node import quality_assessor_node

    state = {
        "harvested_data": [
            {"title": "Study", "pmid": "1", "source": "PubMed", "summary": "Text", "metadata": {"year": "2025"}},
        ],
        "extension_payloads": {
            "slot_a": {"evidence_synthesis": {"grade_scores": {"overall": "B", "score": 3.0}}},
            "slot_b": {"clinical_analysis": {"pipeline_matrix": []}},
            "slot_c": {},
        },
    }
    result = quality_assessor_node(state)
    assert result["status"] == "quality_assessment_complete"
    slot_c = result["extension_payloads"]["slot_c"]
    assert "quality_assessment" in slot_c
    assert "confidence_grade" in slot_c["quality_assessment"]


def test_quality_assessor_node_handles_empty():
    from src.graph.nodes.quality_assessor_node import quality_assessor_node

    state = {
        "harvested_data": [],
        "extension_payloads": {"slot_a": {}, "slot_b": {}, "slot_c": {}},
    }
    result = quality_assessor_node(state)
    assert result["status"] == "quality_assessment_complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_quality_assessor.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.graph.nodes.quality_assessor_node'`

- [ ] **Step 3: Implement the node**

Create `src/graph/nodes/quality_assessor_node.py`:

```python
"""Quality Assessor workflow node."""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.engines.quality_assessor.agent import create_quality_assessor
from src.graph.contracts import validate_extension_output
from src.graph.state import AgentState


def quality_assessor_node(state: AgentState) -> Dict[str, Any]:
    """Assess data quality and assign confidence grade."""
    logger.info("📊 NODE: QUALITY ASSESSOR")

    try:
        agent = create_quality_assessor()
        harvested_data = state.get("harvested_data", []) or []
        extension_payloads = dict(state.get("extension_payloads", {}) or {})

        slot_a_data = extension_payloads.get("slot_a", {})
        slot_b_data = extension_payloads.get("slot_b", {})

        assessment = agent.assess(harvested_data, slot_a_data, slot_b_data)

        slot_payload = {
            "slot_id": "slot_c",
            "agent_name": "quality_assessor",
            "data": {"quality_assessment": assessment},
            "status": "success",
        }

        is_valid, errors = validate_extension_output(slot_payload)
        if not is_valid:
            logger.warning(f"Quality assessor output contract failed: {errors[:5]}")

        extension_payloads["slot_c"] = slot_payload["data"]

        return {
            "extension_payloads": extension_payloads,
            "status": "quality_assessment_complete",
        }
    except Exception as exc:
        logger.error(f"Quality assessor failed: {exc}")
        return {
            "errors": [f"QualityAssessor: {str(exc)}"],
            "status": "quality_assessment_failed",
        }


__all__ = ["quality_assessor_node"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_quality_assessor.py`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/quality_assessor_node.py tests/test_quality_assessor.py
git commit -m "feat(nodes): add quality_assessor_node writing to slot_c"
```

---

### Task 9: Rewire Topology & Update Node Exports

**Files:**
- Modify: `src/graph/nodes/__init__.py`
- Modify: `src/graph/workflow.py`
- Modify: `tests/test_dataflow_integrity.py` (topology assertions)

- [ ] **Step 1: Write the failing test**

In `tests/test_dataflow_integrity.py`, replace the existing `"Workflow keeps connected harvest-handoff-writer chain"` test with:

```python
@test("Workflow has 6-node linear topology")
def _():
    source = Path("src/graph/workflow.py").read_text(encoding="utf-8")
    assert 'workflow.add_node("harvester"' in source
    assert 'workflow.add_node("extension_handoff"' in source
    assert 'workflow.add_node("evidence_synthesizer"' in source
    assert 'workflow.add_node("clinical_analyzer"' in source
    assert 'workflow.add_node("quality_assessor"' in source
    assert 'workflow.add_node("writer"' in source
    assert 'workflow.add_edge(START, "harvester")' in source
    assert 'workflow.add_edge("harvester", "extension_handoff")' in source
    assert 'workflow.add_edge("extension_handoff", "evidence_synthesizer")' in source
    assert 'workflow.add_edge("evidence_synthesizer", "clinical_analyzer")' in source
    assert 'workflow.add_edge("clinical_analyzer", "quality_assessor")' in source
    assert 'workflow.add_edge("quality_assessor", "writer")' in source
    assert 'workflow.add_edge("writer", END)' in source
    assert 'workflow.add_edge("extension_handoff", "writer")' not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py`
Expected: FAIL — old topology still has `extension_handoff → writer` edge.

- [ ] **Step 3: Update node exports**

Replace `src/graph/nodes/__init__.py` entirely:

```python
"""Workflow node implementations for LangGraph orchestration."""

from .extension_handoff_node import extension_handoff_node
from .harvester_node import harvester_node
from .evidence_synthesizer_node import evidence_synthesizer_node
from .clinical_analyzer_node import clinical_analyzer_node
from .quality_assessor_node import quality_assessor_node
from .writer_node import writer_node

__all__ = [
    "extension_handoff_node",
    "harvester_node",
    "evidence_synthesizer_node",
    "clinical_analyzer_node",
    "quality_assessor_node",
    "writer_node",
]
```

- [ ] **Step 4: Rewire workflow.py**

Replace `src/graph/workflow.py` entirely:

```python
"""LangGraph topology builder for Cassandra workflows."""

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import (
    extension_handoff_node,
    harvester_node,
    evidence_synthesizer_node,
    clinical_analyzer_node,
    quality_assessor_node,
    writer_node,
)
from src.graph.state import AgentState


def create_workflow() -> StateGraph:
    """Build the 6-node Cassandra analysis pipeline.

    Topology:
        START → harvester → extension_handoff → evidence_synthesizer
              → clinical_analyzer → quality_assessor → writer → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("harvester", harvester_node)
    workflow.add_node("extension_handoff", extension_handoff_node)
    workflow.add_node("evidence_synthesizer", evidence_synthesizer_node)
    workflow.add_node("clinical_analyzer", clinical_analyzer_node)
    workflow.add_node("quality_assessor", quality_assessor_node)
    workflow.add_node("writer", writer_node)

    workflow.add_edge(START, "harvester")
    workflow.add_edge("harvester", "extension_handoff")
    workflow.add_edge("extension_handoff", "evidence_synthesizer")
    workflow.add_edge("evidence_synthesizer", "clinical_analyzer")
    workflow.add_edge("clinical_analyzer", "quality_assessor")
    workflow.add_edge("quality_assessor", "writer")
    workflow.add_edge("writer", END)

    return workflow


__all__ = ["create_workflow"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/__init__.py src/graph/workflow.py tests/test_dataflow_integrity.py
git commit -m "feat(topology): rewire to 6-node pipeline with extension agents"
```

---

### Task 10: Writer Node Upgrade — Consume All Three Slots

**Files:**
- Modify: `src/graph/nodes/writer_node.py:71-88` (contract_payload construction)
- Modify: `src/graph/nodes/writer_node.py:101-113` (writer_payload construction)

- [ ] **Step 1: Write the failing test**

Create `tests/test_writer_slot_consumption.py`:

```python
"""Verify writer_node passes extension slot data through to the report agent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from src.graph.nodes.writer_node import writer_node


def _make_state_with_slots():
    return {
        "user_query": "Lung cancer drug landscape",
        "harvested_data": [
            {"title": "Study A", "summary": "OS 12 months", "source": "PubMed", "pmid": "1", "metadata": {}},
        ],
        "harvest_data_layers": {"disease_layer": {}},
        "harvest_source_payloads": {},
        "harvest_frontend_payload": {},
        "extension_payloads": {
            "slot_a": {
                "evidence_synthesis": {
                    "evidence_layers": {"rct": [{"title": "Study A"}]},
                    "grade_scores": {"overall": "B", "score": 3.5},
                }
            },
            "slot_b": {
                "clinical_analysis": {
                    "pipeline_matrix": [{"indication": "NSCLC", "intervention": "Drug X"}],
                    "safety_signals": [],
                }
            },
            "slot_c": {
                "quality_assessment": {
                    "confidence_grade": "B",
                    "confidence_score": 0.72,
                    "rationale": "Acceptable quality.",
                }
            },
        },
        "pdf_paths": [],
        "project_name": "TestProject",
        "dataflow_contract_version": "2026-04-17.v4",
    }


@patch("src.graph.nodes.writer_node.create_report_agent")
@patch("src.graph.nodes.writer_node.build_biomedical_profile")
def test_writer_passes_all_slots_as_synthesis_sections(mock_profile, mock_agent_factory):
    mock_profile.return_value = {
        "disease_areas": [], "drug_baselines": [], "target_signals": [],
        "company_entities": [], "clinical_data": {}, "evidence_stats": {},
    }

    mock_output = MagicMock()
    mock_output.markdown_content = "# Test Report"
    mock_output.markdown_path = "/tmp/test.md"

    mock_agent = MagicMock()
    mock_agent.write_report.return_value = mock_output
    mock_agent_factory.return_value = mock_agent

    state = _make_state_with_slots()
    result = writer_node(state)

    assert result["status"] == "writer_complete"

    call_kwargs = mock_agent.write_report.call_args[1]
    synthesis = call_kwargs["synthesis_sections"]
    assert "slot_a" in synthesis
    assert "slot_b" in synthesis
    assert "slot_c" in synthesis
    assert "evidence_synthesis" in synthesis["slot_a"]
    assert "clinical_analysis" in synthesis["slot_b"]
    assert "quality_assessment" in synthesis["slot_c"]


@patch("src.graph.nodes.writer_node.create_report_agent")
@patch("src.graph.nodes.writer_node.build_biomedical_profile")
def test_writer_includes_analysis_status_with_extensions(mock_profile, mock_agent_factory):
    mock_profile.return_value = {
        "disease_areas": [], "drug_baselines": [], "target_signals": [],
        "company_entities": [], "clinical_data": {}, "evidence_stats": {},
    }

    mock_output = MagicMock()
    mock_output.markdown_content = "# Report"
    mock_output.markdown_path = None

    mock_agent = MagicMock()
    mock_agent.write_report.return_value = mock_output
    mock_agent_factory.return_value = mock_agent

    state = _make_state_with_slots()
    result = writer_node(state)

    call_kwargs = mock_agent.write_report.call_args[1]
    assert call_kwargs["analysis_status"] == "FULL_PIPELINE"


if __name__ == "__main__":
    test_writer_passes_all_slots_as_synthesis_sections()
    print("[PASS] test_writer_passes_all_slots_as_synthesis_sections")
    test_writer_includes_analysis_status_with_extensions()
    print("[PASS] test_writer_includes_analysis_status_with_extensions")
    print("Writer slot consumption tests complete.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_writer_slot_consumption.py`
Expected: FAIL — `analysis_status` is still `"HARVEST_ONLY"`, not `"FULL_PIPELINE"`.

- [ ] **Step 3: Update writer_node.py**

In `src/graph/nodes/writer_node.py`, replace the `writer_node` function (lines 61-144) with:

```python
def writer_node(state: AgentState) -> Dict[str, Any]:
    """Render the final report from harvested data and extension handoff payloads."""
    logger.info("✍️ NODE: REPORT WRITER")

    try:
        agent = create_report_agent()

        harvested_data = state.get("harvested_data", []) or []
        user_query = state.get("user_query", "")
        compiled_context = _build_harvest_context_text(user_query, harvested_data)
        extension_payloads = state.get("extension_payloads", {}) or {}

        has_extensions = any(
            bool(extension_payloads.get(slot))
            for slot in ("slot_a", "slot_b", "slot_c")
        )
        analysis_status = "FULL_PIPELINE" if has_extensions else "HARVEST_ONLY"

        contract_payload = {
            "user_query": user_query,
            "harvest_data": {
                "query": user_query,
                "results": harvested_data,
                "data_layers": state.get("harvest_data_layers", {}),
                "source_payloads": state.get("harvest_source_payloads", {}),
                "frontend_payload": state.get("harvest_frontend_payload", {}),
            },
            "synthesis_sections": extension_payloads,
            "project_name": state.get("project_name"),
            "output_dir": "final_reports",
            "compiled_context_text": compiled_context,
            "analysis_status": analysis_status,
            "contract_version": CONTRACT_VERSION,
        }

        is_valid, errors = validate_writer_input(contract_payload)
        if not is_valid:
            logger.error("Writer input contract validation failed")
            for err in errors[:10]:
                logger.error(f"  - {err}")
            return {
                "final_report": "# Contract Validation Failed\n\nWriter input payload did not pass schema validation.",
                "errors": [f"Writer contract: {err}" for err in errors],
                "status": "writer_failed",
            }

        writer_payload = {
            "user_query": user_query,
            "harvest_data": contract_payload["harvest_data"],
            "synthesis_sections": extension_payloads,
            "project_name": state.get("project_name"),
            "output_dir": "final_reports",
            "compiled_context_text": compiled_context,
            "failed_count": 0,
            "total_files": len(state.get("pdf_paths", []) or []),
            "analysis_status": analysis_status,
            "failed_files": [],
            "contract_version": CONTRACT_VERSION,
        }

        report_output = agent.write_report(**writer_payload)
        markdown = report_output.markdown_content if hasattr(report_output, "markdown_content") else str(report_output)

        state_with_project = dict(state)
        if not state_with_project.get("project_name"):
            state_with_project["project_name"] = user_query.strip() or "Unknown"
        biomedical_profile = build_biomedical_profile(state_with_project)

        return {
            "final_report": markdown,
            "final_report_markdown": markdown,
            "final_report_path": getattr(report_output, "markdown_path", None),
            "analysis_focus": analysis_status,
            "extension_payloads": extension_payloads,
            "biomedical_profile": biomedical_profile,
            "disease_areas": biomedical_profile.get("disease_areas", []),
            "drug_baselines": biomedical_profile.get("drug_baselines", []),
            "target_signals": biomedical_profile.get("target_signals", []),
            "company_entities": biomedical_profile.get("company_entities", []),
            "clinical_data": biomedical_profile.get("clinical_data", {}),
            "evidence_stats": biomedical_profile.get("evidence_stats", {}),
            "status": "writer_complete",
        }
    except Exception as exc:
        logger.error(f"Writer failed: {exc}")
        return {
            "final_report": f"# Report Generation Failed\n\nError: {str(exc)}",
            "errors": [f"Writer: {str(exc)}"],
            "status": "writer_failed",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_writer_slot_consumption.py`
Expected: All PASS.

- [ ] **Step 5: Run full regression**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/graph/nodes/writer_node.py tests/test_writer_slot_consumption.py
git commit -m "feat(writer): consume slot_a/slot_b/slot_c, auto-detect FULL_PIPELINE status"
```

---

### Task 11: Final Integration — Supervisor & Full Regression

**Files:**
- Modify: `src/agents/supervisor.py:90-117` (update `_initial_state` docstring)
- Modify: `tests/test_dataflow_integrity.py` (add end-to-end node import test)

- [ ] **Step 1: Update supervisor _initial_state docstring**

In `src/agents/supervisor.py`, update the docstring of `_initial_state` (around line 91) to:

```python
def _initial_state(user_query: str, pdf_paths: Optional[List[str]] = None) -> AgentState:
    """Build initial workflow state for the 6-node analysis pipeline.

    Topology: harvester → extension_handoff → evidence_synthesizer
              → clinical_analyzer → quality_assessor → writer
    """
```

- [ ] **Step 2: Add integration import test**

Add to `tests/test_dataflow_integrity.py`, in the `[1] Import Sanity` section:

```python
@test("Import all six node functions")
def _():
    from src.graph.nodes import (
        harvester_node,
        extension_handoff_node,
        evidence_synthesizer_node,
        clinical_analyzer_node,
        quality_assessor_node,
        writer_node,
    )
    assert all([
        harvester_node,
        extension_handoff_node,
        evidence_synthesizer_node,
        clinical_analyzer_node,
        quality_assessor_node,
        writer_node,
    ])


@test("Import all three extension engines")
def _():
    from src.engines.evidence_synthesizer import EvidenceSynthesizerAgent
    from src.engines.clinical_analyzer import ClinicalAnalyzerAgent
    from src.engines.quality_assessor import QualityAssessorAgent
    assert all([EvidenceSynthesizerAgent, ClinicalAnalyzerAgent, QualityAssessorAgent])


@test("Extension output contract validator exists")
def _():
    from src.graph.contracts import validate_extension_output
    assert callable(validate_extension_output)
```

- [ ] **Step 3: Run full test suite**

Run: `cd "F:/Visual Studio Code/alpha/Cassandra" && python tests/test_dataflow_integrity.py && python tests/test_extension_handoff.py && python tests/test_evidence_synthesizer.py && python tests/test_clinical_analyzer.py && python tests/test_quality_assessor.py && python tests/test_writer_slot_consumption.py`
Expected: All PASS across all test files.

- [ ] **Step 4: Commit**

```bash
cd "F:/Visual Studio Code/alpha/Cassandra"
git add src/agents/supervisor.py tests/test_dataflow_integrity.py
git commit -m "feat: complete 6-node pipeline integration with full regression tests"
```

---

## Post-Implementation Topology

```
START → harvester → extension_handoff → evidence_synthesizer
      → clinical_analyzer → quality_assessor → writer → END
```

| Node | Reads | Writes |
|------|-------|--------|
| `harvester` | `user_query` | `harvested_data`, `harvest_data_layers`, `harvest_source_payloads`, `pdf_paths` |
| `extension_handoff` | `extension_payloads` | `extension_payloads` (slot_a/b/c initialized) |
| `evidence_synthesizer` | `harvested_data`, `harvest_data_layers`, `extension_payloads` | `extension_payloads.slot_a` |
| `clinical_analyzer` | `harvested_data`, `harvest_source_payloads`, `extension_payloads` | `extension_payloads.slot_b` |
| `quality_assessor` | `harvested_data`, `extension_payloads.slot_a`, `extension_payloads.slot_b` | `extension_payloads.slot_c` |
| `writer` | all state fields + `extension_payloads.*` | `final_report`, `biomedical_profile`, etc. |
