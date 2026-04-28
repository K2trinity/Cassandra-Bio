import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import app as app_module


def _fragment(*parts: str) -> str:
    return "".join(parts)


def test_request_report_bridges_into_main_analysis_queue(monkeypatch):
    def fake_analyze():
        return app_module.jsonify({
            "status": "accepted",
            "message": "Analysis started. Monitor progress via WebSocket.",
            "query": "stub",
            "task_id": "task-123",
        }), 202

    monkeypatch.setattr(app_module, "analyze", fake_analyze)

    client = app_module.socketio.test_client(app_module.app)
    client.emit(_fragment("request", "_", "report"), {
        "ticker": "MRNA",
        "event_id": "evt_001",
        "event_type": "clinical_readout",
        "date": "2026-04-20",
        "catalyst": "Phase 3 trial positive results",
    })
    received = client.get_received()

    assert any(
        packet["name"] == "report_queued" and packet["args"][0]["task_id"] == "task-123"
        for packet in received
    )
