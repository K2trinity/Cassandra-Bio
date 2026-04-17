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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
    print("Evidence synthesizer tests complete.")
