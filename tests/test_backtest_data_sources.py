from __future__ import annotations

import pytest


def test_yfinance_profile_is_survivorship_biased():
    from src.backtest.data_sources import BiasProfile, YFINANCE_PROFILE

    assert YFINANCE_PROFILE.source_id == "yfinance"
    assert YFINANCE_PROFILE.bias_profile == BiasProfile.SURVIVORSHIP_BIASED
    assert YFINANCE_PROFILE.supports_delisted is False


def test_yfinance_allowed_for_exploratory_mode():
    from src.backtest.data_sources import BacktestMode, YFINANCE_PROFILE
    from src.backtest.data_sources import validate_source_for_mode

    result = validate_source_for_mode(YFINANCE_PROFILE, BacktestMode.EXPLORATORY)

    assert result.allowed is True
    assert result.bias_warnings == [
        "Source yfinance is survivorship-biased and is not research-grade."
    ]


def test_yfinance_blocked_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode, SourcePolicyError, YFINANCE_PROFILE
    from src.backtest.data_sources import validate_source_for_mode

    with pytest.raises(SourcePolicyError, match="research-grade"):
        validate_source_for_mode(YFINANCE_PROFILE, BacktestMode.RESEARCH_GRADE)
