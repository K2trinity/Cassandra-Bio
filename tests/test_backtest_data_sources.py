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
    assert result.bias_warnings == (
        "Source yfinance is survivorship-biased and is not research-grade.",
    )


def test_yfinance_blocked_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode, SourcePolicyError, YFINANCE_PROFILE
    from src.backtest.data_sources import validate_source_for_mode

    with pytest.raises(SourcePolicyError, match="research-grade") as exc_info:
        validate_source_for_mode(YFINANCE_PROFILE, BacktestMode.RESEARCH_GRADE)
    assert str(exc_info.value) == (
        "Source yfinance cannot be used for research-grade backtests "
        "because it is not survivorship-bias-free."
    )


def test_yfinance_blocked_for_mock_mode():
    from src.backtest.data_sources import BacktestMode, SourcePolicyError, YFINANCE_PROFILE
    from src.backtest.data_sources import validate_source_for_mode

    with pytest.raises(SourcePolicyError, match="yfinance.*mock mode"):
        validate_source_for_mode(YFINANCE_PROFILE, BacktestMode.MOCK)


def test_mock_profile_allowed_for_mock_mode():
    from src.backtest.data_sources import BacktestMode, BiasProfile, MOCK_PROFILE
    from src.backtest.data_sources import validate_source_for_mode

    result = validate_source_for_mode(MOCK_PROFILE, BacktestMode.MOCK)

    assert result.allowed is True
    assert result.bias_profile == BiasProfile.MOCK
    assert result.bias_warnings == ()


def test_spoofed_mock_bias_source_id_rejected_for_mock_mode():
    from src.backtest.data_sources import BacktestMode, BiasProfile, SourcePolicyError
    from src.backtest.data_sources import SourceProfile, validate_source_for_mode

    profile = SourceProfile(
        source_id="yfinance",
        display_name="Spoofed",
        bias_profile=BiasProfile.MOCK,
        supports_delisted=False,
        supports_point_in_time_universe=False,
        supports_delisting_returns=False,
    )

    with pytest.raises(SourcePolicyError, match="yfinance.*mock mode"):
        validate_source_for_mode(profile, BacktestMode.MOCK)


def test_mock_profile_rejected_for_exploratory_mode():
    from src.backtest.data_sources import BacktestMode, MOCK_PROFILE, SourcePolicyError
    from src.backtest.data_sources import validate_source_for_mode

    with pytest.raises(SourcePolicyError, match="mock.*mock mode"):
        validate_source_for_mode(MOCK_PROFILE, BacktestMode.EXPLORATORY)


def test_research_grade_requires_full_survivorship_coverage():
    from src.backtest.data_sources import BacktestMode, BiasProfile, SourcePolicyError
    from src.backtest.data_sources import SourceProfile, validate_source_for_mode

    incomplete_profile = SourceProfile(
        source_id="partial_bias_free",
        display_name="Partial bias-free source",
        bias_profile=BiasProfile.SURVIVORSHIP_BIAS_FREE,
        supports_delisted=True,
        supports_point_in_time_universe=False,
        supports_delisting_returns=True,
    )

    with pytest.raises(SourcePolicyError, match="research-grade coverage"):
        validate_source_for_mode(incomplete_profile, BacktestMode.RESEARCH_GRADE)


def test_research_grade_allows_fully_capable_bias_free_source():
    from src.backtest.data_sources import BacktestMode, BiasProfile, SourceProfile
    from src.backtest.data_sources import validate_source_for_mode

    complete_profile = SourceProfile(
        source_id="complete_bias_free",
        display_name="Complete bias-free source",
        bias_profile=BiasProfile.SURVIVORSHIP_BIAS_FREE,
        supports_delisted=True,
        supports_point_in_time_universe=True,
        supports_delisting_returns=True,
    )

    result = validate_source_for_mode(complete_profile, BacktestMode.RESEARCH_GRADE)

    assert result.allowed is True
    assert result.bias_profile == BiasProfile.SURVIVORSHIP_BIAS_FREE
    assert result.bias_warnings == ()
