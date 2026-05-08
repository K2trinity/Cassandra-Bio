from __future__ import annotations


def _insert_membership(
    db_path,
    *,
    universe_id: str = "biotech_us_v1",
    security_id: str,
    ticker: str | None,
    member_from: str,
    member_to: str | None = None,
) -> None:
    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO universe_membership (
                universe_id,
                security_id,
                ticker,
                member_from,
                member_to,
                weight,
                membership_source,
                as_of_date
            )
            VALUES (?, ?, ?, ?, ?, NULL, 'test', ?)
            """,
            [
                universe_id,
                security_id,
                ticker,
                member_from,
                member_to,
                member_from,
            ],
        )
    finally:
        conn.close()


def test_load_universe_tickers_returns_active_members_sorted_and_uppercased(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import load_universe_tickers

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    _insert_membership(
        db_path,
        security_id="BIO:VRTX",
        ticker="vrtx",
        member_from="2024-01-01",
    )
    _insert_membership(
        db_path,
        security_id="BIO:MRNA",
        ticker="mrna",
        member_from="2024-01-01",
        member_to="2026-01-15",
    )
    _insert_membership(
        db_path,
        security_id="BIO:BIIB",
        ticker="BIIB",
        member_from="2025-01-01",
        member_to="2026-05-08",
    )
    _insert_membership(
        db_path,
        security_id="BIO:SGEN",
        ticker="SGEN",
        member_from="2026-05-09",
    )
    _insert_membership(
        db_path,
        security_id="BIO:ALT",
        ticker="ALT",
        universe_id="other_universe",
        member_from="2024-01-01",
    )

    assert load_universe_tickers(
        db_path=db_path,
        universe_id="biotech_us_v1",
        as_of_date="2026-05-08",
    ) == ("BIIB", "VRTX")


def test_load_universe_tickers_rejects_non_production_universe(tmp_path):
    import pytest

    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import UnsupportedUniverseError, load_universe_tickers

    db_path = initialize_research_database(tmp_path / "research.duckdb")

    with pytest.raises(
        UnsupportedUniverseError,
        match="^Unsupported production universe: biotech_mock_v1$",
    ):
        load_universe_tickers(
            db_path=db_path,
            universe_id="biotech_mock_v1",
            as_of_date="2026-05-08",
        )


def test_load_universe_tickers_ignores_invalid_catalog_tickers(tmp_path):
    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import load_universe_tickers

    db_path = initialize_research_database(tmp_path / "research.duckdb")
    _insert_membership(
        db_path,
        security_id="BIO:NULL",
        ticker=None,
        member_from="2024-01-01",
    )
    _insert_membership(
        db_path,
        security_id="BIO:BLANK",
        ticker="",
        member_from="2024-01-01",
    )
    _insert_membership(
        db_path,
        security_id="BIO:SPACE",
        ticker="   ",
        member_from="2024-01-01",
    )
    _insert_membership(
        db_path,
        security_id="BIO:BAD",
        ticker=" ../BAD",
        member_from="2024-01-01",
    )
    _insert_membership(
        db_path,
        security_id="BIO:MRNA",
        ticker=" mrna ",
        member_from="2024-01-01",
    )

    assert load_universe_tickers(
        db_path=db_path,
        universe_id="biotech_us_v1",
        as_of_date="2026-05-08",
    ) == ("MRNA",)


def test_load_universe_tickers_rejects_invalid_as_of_date(tmp_path):
    import pytest

    from src.backtest.research_db import initialize_research_database
    from src.backtest.universe import load_universe_tickers

    db_path = initialize_research_database(tmp_path / "research.duckdb")

    for as_of_date in ["", "   ", "2026-5-8", "2026-02-30"]:
        with pytest.raises(ValueError, match="as_of_date must use YYYY-MM-DD format"):
            load_universe_tickers(
                db_path=db_path,
                universe_id="biotech_us_v1",
                as_of_date=as_of_date,
            )
