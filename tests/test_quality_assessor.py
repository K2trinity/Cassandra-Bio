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
