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
