"""Regression checks after removing Evidence/Forensic engine coupling."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_no_legacy_engine_imports_in_core_modules():
    core_files = [
        Path("src/agents/supervisor.py"),
        Path("src/graph/workflow.py"),
        Path("src/graph/nodes/harvester_node.py"),
        Path("src/graph/nodes/writer_node.py"),
        Path("app.py"),
    ]

    for file_path in core_files:
        text = file_path.read_text(encoding="utf-8")
        assert "EvidenceEngine" not in text, f"Found EvidenceEngine reference in {file_path}"
        assert "ForensicEngine" not in text, f"Found ForensicEngine reference in {file_path}"


def test_graph_nodes_directory_keeps_connected_extension_chain_nodes():
    nodes_dir = Path("src/graph/nodes")
    names = {p.name for p in nodes_dir.glob("*.py")}

    assert "harvester_node.py" in names
    assert "extension_handoff_node.py" in names
    assert "writer_node.py" in names
    assert "analyzer_node.py" not in names
    assert "figure_node.py" not in names
    assert "synthesizer_node.py" not in names


def test_writer_contract_accepts_harvest_only_payload():
    from src.graph.contracts import validate_writer_input

    payload = {
        "user_query": "Glioblastoma treatment landscape",
        "harvest_data": {"results": []},
        "output_dir": "final_reports",
        "contract_version": "2026-04-14.v3",
    }

    ok, errors = validate_writer_input(payload)
    assert ok, f"Unexpected schema validation errors: {errors}"
