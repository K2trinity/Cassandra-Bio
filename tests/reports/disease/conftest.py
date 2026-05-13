from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_report_events_db(tmp_path, monkeypatch):
    """Keep report-pipeline tests from mutating the persistent K-line event store."""
    from src.backtest import events_db

    monkeypatch.setattr(events_db, "DB_PATH", tmp_path / "events.db")
