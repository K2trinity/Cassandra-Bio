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


def test_date_only_event_uses_requested_security_price_dates():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-mrna-date-only",
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )
    prices = pd.DataFrame(
        [
            {"security_id": "YFINANCE:JNJ", "date": "2026-04-21"},
            {"security_id": "YFINANCE:MRNA", "date": "2026-04-22"},
        ]
    )

    links = align_events_for_snapshot(
        events,
        prices,
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["security_id"] == "YFINANCE:MRNA"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-22"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-22"
    assert links.iloc[0]["alignment_rule"] == "date_only_next_trading_day"
    assert links.iloc[0]["price_date_available"] is True


def test_price_dates_for_other_security_do_not_make_requested_security_available():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-mrna-unavailable",
                "date": "2026-04-20",
                "ticker_scope": "MRNA",
            }
        ]
    )
    prices = pd.DataFrame(
        [
            {"security_id": "YFINANCE:JNJ", "date": "2026-04-21"},
        ]
    )

    links = align_events_for_snapshot(
        events,
        prices,
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["security_id"] == "YFINANCE:MRNA"
    assert links.iloc[0]["aligned_signal_date"] is None
    assert links.iloc[0]["aligned_trade_date"] is None
    assert links.iloc[0]["alignment_rule"] == "outside_price_window"
    assert links.iloc[0]["price_date_available"] is False


def test_numeric_yyyymmdd_event_and_price_dates_parse_as_calendar_dates():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-numeric-date",
                "date": 20260420,
                "ticker_scope": "MRNA",
            }
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": 20260420},
            {"date": 20260421},
        ]
    )

    links = align_events_for_snapshot(
        events,
        prices,
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["original_event_date"] == "2026-04-20"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"


def test_invalid_numeric_event_date_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-invalid-numeric-date",
                "date": 123,
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="date"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id="YFINANCE:MRNA",
        )


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


@pytest.mark.parametrize("release_session", ["premarket", "pre-market", "pre_market"])
def test_premarket_release_session_aliases_align_same_day(release_session):
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-premarket-alias",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T11:00:00Z",
                "release_session": release_session,
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

    assert links.iloc[0]["release_session"] == "pre_market"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-20"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-20"
    assert links.iloc[0]["alignment_rule"] == "pre_market_same_trading_day"


@pytest.mark.parametrize(
    "release_session",
    ["afterclose", "after-close", "after_close"],
)
def test_after_close_release_session_aliases_align_next_day(release_session):
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-after-close-alias",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T22:05:00Z",
                "release_session": release_session,
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

    assert links.iloc[0]["release_session"] == "after_close"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"
    assert links.iloc[0]["alignment_rule"] == "after_close_next_trading_day"


def test_unknown_release_session_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-unknown-release-session",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20T16:00:00Z",
                "release_session": "midday",
                "ticker_scope": "MRNA",
            }
        ]
    )

    with pytest.raises(ValueError, match="release_session"):
        align_events_for_snapshot(
            events,
            _prices(),
            data_snapshot_id="snap-test",
            security_id="YFINANCE:MRNA",
        )


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


def test_invalid_numeric_price_date_is_ignored_not_1970():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-valid-after-invalid-price",
                "date": 20260420,
                "ticker_scope": "MRNA",
            }
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": 123},
            {"date": 20260421},
        ]
    )

    links = align_events_for_snapshot(
        events,
        prices,
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )

    assert links.iloc[0]["original_event_date"] == "2026-04-20"
    assert links.iloc[0]["aligned_signal_date"] == "2026-04-21"
    assert links.iloc[0]["aligned_trade_date"] == "2026-04-21"


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


def test_date_only_timestamp_text_raises_value_error():
    from src.backtest.event_alignment import align_events_for_snapshot

    events = pd.DataFrame(
        [
            {
                "id": "evt-date-only-ts",
                "date": "2026-04-20",
                "event_timestamp_utc": "2026-04-20",
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


def test_write_event_price_links_rejects_mismatched_aligned_dates(tmp_path):
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
    links.loc[0, "aligned_trade_date"] = "2026-04-21"

    with pytest.raises(ValueError, match="aligned_trade_date"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")


def test_write_event_price_links_rejects_unavailable_row_with_aligned_dates(tmp_path):
    from src.backtest.event_alignment import (
        align_events_for_snapshot,
        write_event_price_links,
    )

    links = align_events_for_snapshot(
        pd.DataFrame(
            [
                {
                    "id": "evt-too-late",
                    "date": "2026-05-01",
                    "ticker_scope": "MRNA",
                }
            ]
        ),
        _prices(),
        data_snapshot_id="snap-test",
        security_id="YFINANCE:MRNA",
    )
    links.loc[0, "aligned_signal_date"] = "2026-04-22"

    with pytest.raises(ValueError, match="price_date_available"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")


def test_write_event_price_links_validates_original_event_date(tmp_path):
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
    links["original_event_date"] = links["original_event_date"].astype(object)
    links.loc[0, "original_event_date"] = 123

    with pytest.raises(ValueError, match="original_event_date"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")


def test_write_event_price_links_validates_timestamp_text(tmp_path):
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
    links.loc[0, "event_timestamp_utc"] = "2026-04-20"

    with pytest.raises(ValueError, match="event_timestamp_utc"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")


def test_write_event_price_links_rejects_null_price_date_available(tmp_path):
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
    links.loc[0, "price_date_available"] = pd.NA

    with pytest.raises(ValueError, match="price_date_available"):
        write_event_price_links(links, output_root=tmp_path / "event_price_links")
