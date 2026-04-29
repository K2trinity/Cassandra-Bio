from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_events_db(monkeypatch, tmp_path):
    from src.backtest import events_db

    db_path = tmp_path / "events.db"
    monkeypatch.setattr(events_db, "DB_PATH", db_path)
    yield


def _event(event_id: str, **overrides: object) -> dict:
    event = {
        "id": event_id,
        "date": "2026-04-20",
        "type": "clinical_readout",
        "priority": 2,
        "ticker": "MRNA",
        "disease_area": "Oncology",
        "catalyst": "Clinical Trial: Phase 2 readout",
        "sentiment": "positive",
        "price_impact": None,
        "source": "clinicaltrials",
        "source_ids": ["NCT00000001"],
        "metadata": {},
    }
    event.update(overrides)
    return event


def _trusted_event(event_id: str, **overrides: object) -> dict:
    event = _event(
        event_id,
        ticker_scope="MRNA",
        source_run_id="clinicaltrials:MRNA:20260420T000000Z:12345678",
        query_hash="trustedqueryhash",
        company_identity="Moderna, Inc.",
        ownership_status="owned",
        trust_status="trusted",
        schema_version=2,
        quarantine_reason=None,
    )
    event.update(overrides)
    return event


def test_legacy_rows_are_excluded_from_trusted_chart_reads():
    from src.backtest.events_db import (
        get_events_for_chart,
        get_trusted_events_for_chart,
        insert_event,
    )

    insert_event(_event("legacy-mrna", source_ids=[], metadata={}))

    rows = get_events_for_chart("MRNA")

    assert [row["id"] for row in rows] == ["legacy-mrna"]
    assert get_trusted_events_for_chart("MRNA") == []


def test_trusted_reads_require_ticker_scope_and_schema_version():
    from src.backtest.events_db import get_trusted_events_for_chart, insert_events

    insert_events(
        [
            _trusted_event("trusted-mrna"),
            _trusted_event("wrong-scope", ticker_scope="PFE"),
            _trusted_event("old-schema", schema_version=1),
            _trusted_event(
                "quarantined",
                trust_status="quarantined",
                quarantine_reason="ambiguous ownership",
            ),
        ]
    )

    rows = get_trusted_events_for_chart("MRNA")

    assert [row["id"] for row in rows] == ["trusted-mrna"]


def test_trusted_chart_reads_reject_disallowed_ownership_status():
    from src.backtest.events_db import get_trusted_events_for_chart, insert_events

    insert_events(
        [
            _trusted_event("trusted-mrna"),
            _trusted_event("unknown-owner", ownership_status="unknown"),
            _trusted_event("unowned", ownership_status="unowned"),
        ]
    )

    rows = get_trusted_events_for_chart("MRNA")

    assert [row["id"] for row in rows] == ["trusted-mrna"]


def test_trusted_backtest_reads_require_explicit_boolean_backtest_eligible():
    from src.backtest.events_db import get_trusted_events_for_backtest, insert_events

    insert_events(
        [
            _trusted_event("eligible", metadata={"backtest_eligible": True}),
            _trusted_event("visual-only", metadata={"backtest_eligible": False}),
            _trusted_event("string-true", metadata={"backtest_eligible": "true"}),
            _trusted_event("numeric-one", metadata={"backtest_eligible": 1}),
        ]
    )

    rows = get_trusted_events_for_backtest(
        "MRNA",
        start_date="2026-04-20",
        end_date="2026-04-20",
    )

    assert rows["id"].tolist() == ["eligible"]
    assert rows.iloc[0]["metadata"] == {"backtest_eligible": True}


def test_mark_legacy_events_untrusted_updates_missing_schema():
    from src.backtest.events_db import (
        _get_conn,
        init_db,
        insert_event,
        mark_legacy_events_untrusted,
    )

    init_db()
    insert_event(_event("legacy-mrna", source_ids=[], metadata={}))

    updated = mark_legacy_events_untrusted("MRNA")

    conn = _get_conn()
    row = conn.execute(
        """
        SELECT trust_status, schema_version, quarantine_reason
        FROM biotech_events
        WHERE id = ?
        """,
        ("legacy-mrna",),
    ).fetchone()
    conn.close()

    assert updated == 1
    assert (
        row["trust_status"],
        row["schema_version"],
        row["quarantine_reason"],
    ) == ("legacy_untrusted", 1, "legacy row missing trust provenance")


def test_mark_legacy_events_untrusted_normalizes_schema_version_for_all_updated_rows():
    from src.backtest.events_db import (
        _get_conn,
        init_db,
        mark_legacy_events_untrusted,
    )

    init_db()
    conn = _get_conn()
    conn.executemany(
        """
        INSERT INTO biotech_events (
            id, date, type, priority, ticker, trust_status, schema_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("schema-zero", "2026-04-20", "clinical_readout", 2, "MRNA", "trusted", 0),
            ("blank-trust", "2026-04-20", "clinical_readout", 2, "MRNA", "", 2),
        ],
    )
    conn.commit()
    conn.close()

    updated = mark_legacy_events_untrusted("MRNA")

    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, trust_status, schema_version
        FROM biotech_events
        WHERE id IN (?, ?)
        ORDER BY id
        """,
        ("schema-zero", "blank-trust"),
    ).fetchall()
    conn.close()

    assert updated == 2
    assert {
        row["id"]: (row["trust_status"], row["schema_version"])
        for row in rows
    } == {
        "blank-trust": ("legacy_untrusted", 1),
        "schema-zero": ("legacy_untrusted", 1),
    }
