from __future__ import annotations

import pandas as pd


def _prices():
    return pd.DataFrame(
        [
            {"date": "2026-04-20"},
            {"date": "2026-04-21"},
            {"date": "2026-04-22"},
        ]
    )


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
    assert persisted.iloc[0]["aligned_trade_date"] == "2026-04-20"
