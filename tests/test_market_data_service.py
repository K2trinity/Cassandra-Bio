"""Tests for market_data_service with 24h cache freshness logic."""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch, MagicMock
import sys
import os
from types import SimpleNamespace

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.market_data_service import get_ohlc_rows, _is_cache_stale
from src.backtest.data_loader import DATA_DIR


class TestCacheStaleness:
    """Test _is_cache_stale helper."""

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    def test_fresh_cache_returns_false(self, mock_stat, mock_exists):
        """Parquet newer than 24h should return False."""
        mock_exists.return_value = True
        mock_mtime = MagicMock()
        mock_mtime.st_mtime = datetime.now().timestamp()
        mock_stat.return_value = mock_mtime

        path = Path("test.parquet")
        assert _is_cache_stale(path, max_age_hours=24) is False

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    def test_stale_cache_returns_true(self, mock_stat, mock_exists):
        """Parquet older than 24h should return True."""
        mock_exists.return_value = True
        old_time = (datetime.now() - timedelta(hours=25)).timestamp()
        mock_mtime = MagicMock()
        mock_mtime.st_mtime = old_time
        mock_stat.return_value = mock_mtime

        path = Path("test.parquet")
        assert _is_cache_stale(path, max_age_hours=24) is True

    @patch("pathlib.Path.exists")
    def test_nonexistent_file_returns_true(self, mock_exists):
        """Nonexistent file should be considered stale."""
        mock_exists.return_value = False
        path = Path("nonexistent.parquet")
        assert _is_cache_stale(path, max_age_hours=24) is True


class TestGetOhlcRows:
    """Test get_ohlc_rows public function."""

    @patch("src.services.market_data_service.load_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_fresh_cache_calls_load_ohlc(self, mock_stale, mock_load):
        """Fresh cache should call load_ohlc."""
        mock_stale.return_value = False
        mock_load.return_value = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=2),
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1000, 2000],
        })

        result = get_ohlc_rows("TEST", max_age_hours=24)

        mock_stale.assert_called_once()
        mock_load.assert_called_once_with("TEST")
        assert len(result) == 2
        assert result[0]["date"] == "2024-01-01"
        assert result[0]["close"] == 100.5

    @patch("src.services.market_data_service.refresh_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_stale_cache_calls_refresh_ohlc(self, mock_stale, mock_refresh):
        """Stale cache should call refresh_ohlc."""
        mock_stale.return_value = True
        mock_refresh.return_value = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=1),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })

        result = get_ohlc_rows("TEST", max_age_hours=24)

        mock_stale.assert_called_once()
        mock_refresh.assert_called_once_with("TEST")
        assert len(result) == 1
        assert result[0]["date"] == "2024-01-01"

    @patch("src.services.market_data_service.refresh_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_refresh_returns_empty_returns_empty_list(self, mock_stale, mock_refresh):
        """Refresh returning empty DataFrame should return empty list."""
        mock_stale.return_value = True
        mock_refresh.return_value = pd.DataFrame()

        result = get_ohlc_rows("TEST", max_age_hours=24)

        assert result == []

    @patch("src.services.market_data_service.load_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_load_returns_empty_returns_empty_list(self, mock_stale, mock_load):
        """Load returning empty DataFrame should return empty list."""
        mock_stale.return_value = False
        mock_load.return_value = pd.DataFrame()

        result = get_ohlc_rows("TEST", max_age_hours=24)

        assert result == []

    @patch("src.services.market_data_service.load_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_date_serialization_to_yyyy_mm_dd(self, mock_stale, mock_load):
        """Dates should be serialized as YYYY-MM-DD strings."""
        mock_stale.return_value = False
        mock_load.return_value = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-15", "2024-02-20"]),
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1000, 2000],
        })

        result = get_ohlc_rows("TEST", max_age_hours=24)

        assert result[0]["date"] == "2024-01-15"
        assert result[1]["date"] == "2024-02-20"

    @patch("src.services.market_data_service.load_ohlc")
    @patch("src.services.market_data_service.refresh_ohlc")
    @patch("src.services.market_data_service._is_cache_stale")
    def test_refresh_failure_returns_stale_cache_status(
        self,
        mock_stale,
        mock_refresh,
        mock_load,
        tmp_path,
        monkeypatch,
    ):
        """Refresh failures should preserve stale cache visibility and status."""
        from src.services import market_data_service

        mock_stale.return_value = True
        mock_refresh.side_effect = RuntimeError("429 Too Many Requests")
        monkeypatch.setattr(market_data_service, "DATA_DIR", tmp_path)
        (tmp_path / "TEST.parquet").write_bytes(b"cached")
        mock_load.return_value = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=1),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })

        result = market_data_service.get_ohlc_rows_with_status(
            "TEST",
            max_age_hours=24,
        )

        assert result["status"] == "stale"
        assert result["message"] == "429 Too Many Requests"
        assert result["rows"][0]["date"] == "2024-01-01"

    def test_refresh_failure_uses_existing_stale_parquet_without_deleting_it(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Stale fallback should work with real data_loader cache semantics."""
        from src.backtest import data_loader
        from src.services import market_data_service

        cached = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=1),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })
        cache_path = tmp_path / "REALSTALE.parquet"
        cached.to_parquet(cache_path, index=False)

        def fail_download(*args, **kwargs):
            raise RuntimeError("429 Too Many Requests")

        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
        monkeypatch.setattr(market_data_service, "DATA_DIR", tmp_path)
        monkeypatch.setattr(market_data_service, "_is_cache_stale", lambda path, max_age_hours: True)
        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fail_download))

        result = market_data_service.get_ohlc_rows_with_status(
            "REALSTALE",
            max_age_hours=24,
        )

        assert cache_path.exists()
        assert result["status"] == "stale"
        assert result["message"] == "429 Too Many Requests"
        assert result["rows"] == [
            {
                "date": "2024-01-01",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ]

    def test_cached_ohlc_rows_with_status_reads_stale_cache_without_refresh(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Cache-first workspace loads must not call refresh_ohlc."""
        from src.services import market_data_service

        cached = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=1),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })
        cached.to_parquet(tmp_path / "CACHEONLY.parquet", index=False)
        monkeypatch.setattr(market_data_service, "DATA_DIR", tmp_path)
        monkeypatch.setattr(
            market_data_service,
            "refresh_ohlc",
            lambda ticker: (_ for _ in ()).throw(AssertionError("refresh called")),
        )
        monkeypatch.setattr(
            market_data_service,
            "_is_cache_stale",
            lambda path, max_age_hours: True,
        )

        result = market_data_service.get_cached_ohlc_rows_with_status("CACHEONLY")

        assert result["status"] == "stale"
        assert result["message"] == "cached OHLC is stale; refresh pending"
        assert result["rows"][0]["date"] == "2024-01-01"

    def test_cached_ohlc_rows_with_status_returns_empty_without_download(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Missing cache should produce an empty payload, not a yfinance fetch."""
        from src.services import market_data_service

        monkeypatch.setattr(market_data_service, "DATA_DIR", tmp_path)
        monkeypatch.setattr(
            market_data_service,
            "refresh_ohlc",
            lambda ticker: (_ for _ in ()).throw(AssertionError("refresh called")),
        )
        monkeypatch.setattr(
            market_data_service,
            "load_ohlc",
            lambda ticker: (_ for _ in ()).throw(AssertionError("load called")),
        )

        result = market_data_service.get_cached_ohlc_rows_with_status("MISS")

        assert result == {
            "rows": [],
            "status": "empty",
            "message": "no cached OHLC available",
        }

    def test_cached_ohlc_rows_with_status_reads_latest_tiingo_research_snapshot(
        self,
        tmp_path,
        monkeypatch,
    ):
        """K-line cache-first loads should use the research Tiingo snapshot."""
        from src.backtest.price_snapshot import write_prices_daily_frame
        from src.backtest.research_db import initialize_research_database
        from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices
        from src.services import market_data_service

        research_dir = tmp_path / "research"
        db_path = initialize_research_database(research_dir / "cassandra_research.duckdb")
        import duckdb

        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                """
                INSERT INTO data_snapshots (
                    data_snapshot_id,
                    snapshot_date,
                    price_source,
                    event_source_db,
                    universe_id,
                    bias_profile,
                    price_partition_root,
                    event_snapshot_hash,
                    security_master_hash,
                    coverage_json,
                    created_at
                )
                VALUES (
                    'snap_20260513_tiingo',
                    '2026-05-13',
                    'tiingo',
                    'events.db',
                    'biotech_us_v1',
                    'current_constituents_only',
                    'data/research/prices_daily',
                    'events',
                    'security',
                    '{}',
                    CURRENT_TIMESTAMP
                )
                """
            )
        finally:
            conn.close()
        frame = normalize_tiingo_eod_prices(
            [
                {
                    "date": "2026-05-11T00:00:00.000Z",
                    "open": 10.0,
                    "high": 12.0,
                    "low": 9.0,
                    "close": 11.0,
                    "volume": 1000,
                    "adjOpen": 10.0,
                    "adjHigh": 12.0,
                    "adjLow": 9.0,
                    "adjClose": 11.0,
                    "adjVolume": 1000,
                    "divCash": 0.0,
                    "splitFactor": 1.0,
                }
            ],
            ticker="RARE",
            data_snapshot_id="snap_20260513_tiingo",
        )
        write_prices_daily_frame(frame, output_root=research_dir / "prices_daily")
        monkeypatch.setattr(market_data_service, "RESEARCH_DB_PATH", db_path)
        monkeypatch.setattr(market_data_service, "RESEARCH_DIR", research_dir)
        monkeypatch.setattr(market_data_service, "DATA_DIR", tmp_path / "ohlc")
        monkeypatch.setattr(
            market_data_service,
            "refresh_ohlc",
            lambda ticker: (_ for _ in ()).throw(AssertionError("refresh called")),
        )
        monkeypatch.setattr(
            market_data_service,
            "load_ohlc",
            lambda ticker: (_ for _ in ()).throw(AssertionError("load called")),
        )

        result = market_data_service.get_cached_ohlc_rows_with_status("RARE")

        assert result["status"] == "ready"
        assert result["message"] == "research snapshot snap_20260513_tiingo"
        assert result["rows"] == [
            {
                "date": "2026-05-11",
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 1000.0,
            }
        ]

    def test_cached_ohlc_rows_with_status_prefers_best_research_coverage(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A partial latest snapshot should not hide fuller recent coverage."""
        from src.backtest.price_snapshot import write_prices_daily_frame
        from src.backtest.research_db import initialize_research_database
        from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices
        from src.services import market_data_service

        research_dir = tmp_path / "research"
        db_path = initialize_research_database(research_dir / "cassandra_research.duckdb")
        import duckdb

        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                """
                INSERT INTO data_snapshots (
                    data_snapshot_id,
                    snapshot_date,
                    price_source,
                    event_source_db,
                    universe_id,
                    bias_profile,
                    price_partition_root,
                    event_snapshot_hash,
                    security_master_hash,
                    coverage_json,
                    created_at
                )
                VALUES
                (
                    'snap_20260510_full',
                    '2026-05-10',
                    'tiingo',
                    'events.db',
                    'biotech_us_v1',
                    'current_constituents_only',
                    'data/research/prices_daily',
                    'events',
                    'security',
                    '{}',
                    '2026-05-10T01:00:00'
                ),
                (
                    'snap_20260513_partial',
                    '2026-05-13',
                    'tiingo',
                    'events.db',
                    'biotech_us_v1',
                    'current_constituents_only',
                    'data/research/prices_daily',
                    'events',
                    'security',
                    '{}',
                    '2026-05-13T01:00:00'
                )
                """
            )
        finally:
            conn.close()

        def tiingo_row(date: str, close: float) -> dict:
            return {
                "date": f"{date}T00:00:00.000Z",
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000,
                "adjOpen": close - 1,
                "adjHigh": close + 1,
                "adjLow": close - 2,
                "adjClose": close,
                "adjVolume": 1000,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }

        full_frame = normalize_tiingo_eod_prices(
            [
                tiingo_row("2026-05-07", 10.0),
                tiingo_row("2026-05-08", 11.0),
                tiingo_row("2026-05-09", 12.0),
            ],
            ticker="MRNA",
            data_snapshot_id="snap_20260510_full",
        )
        partial_frame = normalize_tiingo_eod_prices(
            [tiingo_row("2026-05-12", 13.0)],
            ticker="MRNA",
            data_snapshot_id="snap_20260513_partial",
        )
        write_prices_daily_frame(
            pd.concat([full_frame, partial_frame], ignore_index=True),
            output_root=research_dir / "prices_daily",
        )
        monkeypatch.setattr(market_data_service, "RESEARCH_DB_PATH", db_path)
        monkeypatch.setattr(market_data_service, "RESEARCH_DIR", research_dir)

        result = market_data_service.get_cached_ohlc_rows_with_status("MRNA")

        assert result["status"] == "ready"
        assert result["message"] == "research snapshot snap_20260510_full"
        assert [row["date"] for row in result["rows"]] == [
            "2026-05-07",
            "2026-05-08",
            "2026-05-09",
        ]

    def test_cached_ohlc_rows_with_status_reuses_research_snapshot_payload(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Repeated K-line opens should not rescan research parquet partitions."""
        from src.backtest.research_db import initialize_research_database
        from src.services import market_data_service

        research_dir = tmp_path / "research"
        db_path = initialize_research_database(research_dir / "cassandra_research.duckdb")
        import duckdb

        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                """
                INSERT INTO data_snapshots (
                    data_snapshot_id,
                    snapshot_date,
                    price_source,
                    event_source_db,
                    universe_id,
                    bias_profile,
                    price_partition_root,
                    event_snapshot_hash,
                    security_master_hash,
                    coverage_json,
                    created_at
                )
                VALUES (
                    'snap_cached',
                    '2026-05-13',
                    'tiingo',
                    'events.db',
                    'biotech_us_v1',
                    'current_constituents_only',
                    'data/research/prices_daily',
                    'events',
                    'security',
                    '{}',
                    '2026-05-13T01:00:00'
                )
                """
            )
        finally:
            conn.close()

        calls = []

        def fake_load_prices_daily_ohlc(ticker, *, data_snapshot_id, output_root, source):
            calls.append((ticker, data_snapshot_id, str(output_root), source))
            return pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-05-11"),
                        "open": 10.0,
                        "high": 12.0,
                        "low": 9.0,
                        "close": 11.0,
                        "volume": 1000,
                    }
                ]
            )

        monkeypatch.setattr(market_data_service, "RESEARCH_DB_PATH", db_path)
        monkeypatch.setattr(market_data_service, "RESEARCH_DIR", research_dir)
        monkeypatch.setattr(
            market_data_service,
            "load_prices_daily_ohlc",
            fake_load_prices_daily_ohlc,
        )

        first = market_data_service.get_cached_ohlc_rows_with_status("MRNA")
        first["rows"][0]["close"] = 999.0
        second = market_data_service.get_cached_ohlc_rows_with_status("MRNA")

        assert len(calls) == 1
        assert second["rows"][0]["close"] == 11.0
