"""Data flow integrity regression for harvest/report-only architecture."""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASSED = 0
FAILED = 0
ERRORS = []


def test(name: str):
    def wrapper(fn):
        global PASSED, FAILED
        try:
            fn()
            PASSED += 1
            print(f"  [PASS] {name}")
        except Exception as exc:
            FAILED += 1
            ERRORS.append((name, str(exc)))
            print(f"  [FAIL] {name}: {exc}")
            traceback.print_exc()

    return wrapper


print("\n" + "=" * 60)
print("  Cassandra Data Flow Integrity (Harvest/Report)")
print("=" * 60)


print("\n[1] Import Sanity")


@test("Import AgentState")
def _():
    from src.graph.state import AgentState

    assert AgentState is not None


@test("Import WorkflowService")
def _():
    from src.services.workflow_service import WorkflowService

    assert WorkflowService is not None


print("\n[2] Contract Schema")


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


@test("Writer schema requires harvest-only fields")
def _():
    from src.graph.contracts import WRITER_INPUT_SCHEMA

    required = set(WRITER_INPUT_SCHEMA["required"])
    assert required == {"user_query", "harvest_data", "output_dir", "contract_version"}


@test("Writer schema has no evidence/forensic required fields")
def _():
    from src.graph.contracts import WRITER_INPUT_SCHEMA

    required = WRITER_INPUT_SCHEMA["required"]
    assert "figure_records" not in required
    assert "literature_findings" not in required


@test("Valid harvest-only writer payload passes")
def _():
    from src.graph.contracts import validate_writer_input

    payload = {
        "user_query": "Alzheimer therapy landscape",
        "harvest_data": {"results": [], "stats": {}},
        "output_dir": "final_reports",
        "contract_version": "2026-04-17.v4",
    }

    ok, errors = validate_writer_input(payload)
    assert ok, f"Expected valid payload, got errors: {errors}"


@test("Legacy payload with evidence/forensic keys fails")
def _():
    from src.graph.contracts import validate_writer_input

    payload = {
        "user_query": "test",
        "harvest_data": {},
        "figure_records": [],
        "literature_findings": [],
        "output_dir": "final_reports",
        "contract_version": "2026-04-17.v4",
    }

    ok, _ = validate_writer_input(payload)
    assert not ok


print("\n[3] Source-level Guardrails")


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


@test("Supervisor has no EvidenceEngine/ForensicEngine imports")
def _():
    source = Path("src/agents/supervisor.py").read_text(encoding="utf-8")
    assert "from EvidenceEngine" not in source
    assert "from ForensicEngine" not in source


print("\n" + "=" * 60)
print(f"  Results: {PASSED} passed, {FAILED} failed")
if ERRORS:
    print("\n  Failures:")
    for name, err in ERRORS:
        print(f"    - {name}: {err}")
print("=" * 60 + "\n")

sys.exit(0 if FAILED == 0 else 1)
