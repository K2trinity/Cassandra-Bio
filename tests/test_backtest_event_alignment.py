from __future__ import annotations

import pandas as pd
import pytest


PLAN_EVENT_PRICE_LINK_COLUMNS = [
    "event_id",
    "security_id",
    "ticker_scope",
    "original_event_date",
    "event_timestamp_utc",
    "release_session",
    "aligned_signal_date",
    "aligned_trade_date",
    "alignment_rule",
    "alignment_confidence",
    "price_date_available",
    "data_snapshot_id",
    "created_at",
]


def _prices():
    return pd.DataFrame(
        [
            {"date": "2026-04-20"},
            {"date": "2026-04-21"},
            {"date": "2026-04-22"},
        ]
    )


def test_event_price_link_columns_match_plan_contract():
    from src.backtest.event_alignment import EVENT_PRICE_LINK_COLUMNS

    assert EVENT_PRICE_LINK_COLUMNS == PLAN_EVENT_PRICE_LINK_COLUMNS


def test_date_only_event_aligns_to_next_trading_date():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-sunday",
                "date": "2026-04-19",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["aligned_signal_date"] == "2026-04-20"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-20"
    assert links.iloc[0]["alignment_rule"] == "date_only_next_trading_day"


def test_date_only_event_on_trading_day_aligns_to_next_trading_date():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-date-only",
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["original_event_date"] == "2026-04-20"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"
    assert links.iloc[0]["alignment_rule"] == "date_only_next_trading_day"


def test_after_close_event_aligns_to_next_trading_date():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-after-close",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T22:05:00Z",
                "release_session": "after_close",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"
    assert links.iloc[0]["alignment_rule"] == "after_close_next_trading_day"


def test_pre_market_event_can_align_same_day():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-pre-market",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T11:00:00Z",
                "release_session": "pre_market",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["aligned_signal_date"] == "2026-04-20"
    assert links.iloc[0]["alignment_rule"] == "pre_market_same_trading_day"


def test_out_of_window_event_is_quarantined():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-too-late",
                "date": "2026-05-01",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["aligned_signal_date"] is None
    assert links.iloc[0]["alignment_rule"] == "outside_price_window"
    assert links.iloc[0]["price_date_available"] is False


def test_timestamp_with_unknown_session_aligns_to_next_trading_date():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-unknown-session",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T15:30:00Z",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"
    assert links.iloc[0]["alignment_rule"] == "timestamp_unknown_session_next_trading_day"


def test_valid_timestamp_is_normalized_to_utc_text():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-offset",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T18:05:00-04:00",
                "release_session": "after_close",
                "ticker_scope": "MRNA",
            }
        ]
    )

    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["event_timestamp_utc"] == "2026-04-20T22:05:00Z"


def test_missing_event_id_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="event_id"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id="YFINANCE:MRNA",
        )


def test_missing_ticker_scope_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-missing-scope",
                "date": "2026-04-20",
                "ticker_scope": " ",
            }
        ]
    )

    with pytest.raises(ValueError, match="ticker_scope"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id="YFINANCE:MRNA",
        )


def test_missing_security_id_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-missing-security",
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="security_id"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id=" ",
        )


def test_missing_data_snapshot_id_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-missing-snapshot",
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="data_snapshot_id"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="",
            security_id="YFINANCE:MRNA",
        )


def test_invalid_event_timestamp_utc_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-invalid-ts",
                "date": "2026-04-20",
                "event_timestamp_utc": "not-a-timestamp",
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="event_timestamp_utc"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id="YFINANCE:MRNA",
        )


def test_write_event_price_links_persists_snapshot_parquet(tmp_path):
    from src.backtest.event_alignment import (
        EVENT_PRICE_LINK_COLUMNS,
        align_events_for_snapshot,
        write_event_price_links,
    )

    events = pd.DataFrame(
        [
            {
                "id": "evt-pre-market",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T11:00:00Z",
                "release_session": "pre_market",
                "ticker_scope": "MRNA",
            }
        ]
    )
    links = align_events_for_snapshot(
        events,
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    path = write_event_price_links(links, output_root=tmp_path / "event_price_links")

    assert path == (
        tmp_path
        / "event_price_links"
        / "data_snapshot_id=snap-test"
        / "event_price_links.parquet"
    )
    persisted = pd.read_parquet(path)
    assert list(persisted.columns) == EVENT_PRICE_LINK_COLUMNS
    assert persisted.iloc[0]["event_id"] == "evt-pre-market"
    assert persisted.iloc[0]["security_id"] == "YFINANCE:MRNA"
    assert persisted.iloc[0]["original_event_date"] == "2026-04-20"
    assert persisted.iloc[0]["aligned_trade_date"] == "2026-04-20"
    assert "alignment_confidence" in persisted.columns
    assert "event_date" not in persisted.columns
    assert not list(path.parent.glob("*.tmp"))
    assert not list(path.parent.glob("*.lock"))


def test_write_event_price_links_rejects_existing_output_without_overwrite(tmp_path):
    from src.backtest.event_alignment import (
        align_events_for_snapshot,
        write_event_price_links,
    )

    links = align_events_for_snapshot(
        pd.DataFrame(
            [
                {
                    "id": "evt-pre-market",
                    "date": "2026-04-20",
                    "event_timestamp_utc": "2026-04-20T11:00:00Z",
                    "release_session": "pre_market",
                    "ticker_scope": "MRNA",
                }
            ]
        ),
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )
    output_root = tmp_path / "event_price_links"
    path = write_event_price_links(links, output_root=output_root)
    original_bytes = path.read_bytes()

    with pytest.raises(FileExistsError, match="Event-price links already exist"):
        write_event_price_links(links, output_root=output_root)

    assert path.read_bytes() == original_bytes
    assert not list(path.parent.glob("*.tmp"))
    assert not list(path.parent.glob("*.lock"))


def test_write_event_price_links_rejects_existing_lock_without_removing_it(tmp_path):
    from src.backtest.event_alignment import (
        align_events_for_snapshot,
        write_event_price_links,
    )

    links = align_events_for_snapshot(
        pd.DataFrame(
            [
                {
                    "id": "evt-pre-market",
                    "date": "2026-04-20",
                    "event_timestamp_utc": "2026-04-20T11:00:00Z",
                    "release_session": "pre_market",
                    "ticker_scope": "MRNA",
                }
            ]
        ),
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )
    partition = tmp_path / "event_price_links" / "data_snapshot_id=snap-test"
    partition.mkdir(parents=True)
    lock_path = partition / "event_price_links.lock"
    lock_path.write_text("other-writer", encoding="utf-8")

    with pytest.raises(FileExistsError, match="write lock"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")

    assert lock_path.read_text(encoding="utf-8") == "other-writer"
    assert not list(partition.glob("*.tmp"))
