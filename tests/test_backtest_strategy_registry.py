from __future__ import annotations

import pytest


def test_default_strategy_uses_mock_demo_only_for_a_universe():
    from src.backtest.strategy_registry import default_strategy_for_kline

    assert default_strategy_for_kline("MRNA") == "mock_multifactor_demo"
    assert default_strategy_for_kline("JNJ") == "mock_multifactor_demo"
    assert default_strategy_for_kline("LLY") == "mock_multifactor_demo"
    assert default_strategy_for_kline("ABBA") == "mock_multifactor_demo"
    assert default_strategy_for_kline("PFE") == "event_baseline"


def test_mock_strategy_requires_mock_data_mode_and_scope():
    from src.backtest.strategy_registry import StrategyAccessError, validate_strategy_access

    validate_strategy_access(
        strategy_id="mock_multifactor_demo",
        data_mode="mock",
        mock_scope="biotech_mock_v1",
    )

    with pytest.raises(StrategyAccessError, match="mock_multifactor_demo"):
        validate_strategy_access(
            strategy_id="mock_multifactor_demo",
            data_mode="real",
            mock_scope=None,
        )

    with pytest.raises(StrategyAccessError, match="biotech_mock_v1"):
        validate_strategy_access(
            strategy_id="mock_multifactor_demo",
            data_mode="mock",
            mock_scope="biotech_four_v1",
        )


def test_strategy_registry_fails_closed_for_unknown_strategy_ids():
    from src.backtest.strategy_registry import StrategyAccessError, validate_strategy_access

    with pytest.raises(StrategyAccessError, match="unknown strategy"):
        validate_strategy_access(
            strategy_id="unknown_strategy",
            data_mode="real",
            mock_scope=None,
        )

    with pytest.raises(StrategyAccessError, match="unknown strategy"):
        validate_strategy_access(
            strategy_id="MOCK_MULTIFACTOR_DEMO",
            data_mode="mock",
            mock_scope="biotech_mock_v1",
        )


def test_mock_strategy_requires_exact_mock_data_mode():
    from src.backtest.strategy_registry import StrategyAccessError, validate_strategy_access

    with pytest.raises(StrategyAccessError, match="data_mode"):
        validate_strategy_access(
            strategy_id="mock_multifactor_demo",
            data_mode="Mock",
            mock_scope="biotech_mock_v1",
        )


def test_real_strategies_do_not_need_mock_scope():
    from src.backtest.strategy_registry import validate_strategy_access

    validate_strategy_access(
        strategy_id="event_baseline",
        data_mode="real",
        mock_scope=None,
    )
    validate_strategy_access(
        strategy_id="multifactor_score",
        data_mode="real",
        mock_scope=None,
    )
