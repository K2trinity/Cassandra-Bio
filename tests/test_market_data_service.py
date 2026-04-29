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
