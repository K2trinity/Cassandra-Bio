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
