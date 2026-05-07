from __future__ import annotations

import pytest


def test_default_strategy_uses_real_multifactor_for_kline_backtests():
    from src.backtest.strategy_registry import default_strategy_for_kline

    assert default_strategy_for_kline("MRNA") == "multifactor_score"
    assert default_strategy_for_kline("JNJ") == "multifactor_score"
    assert default_strategy_for_kline("LLY") == "multifactor_score"
    assert default_strategy_for_kline("ABBA") == "multifactor_score"
    assert default_strategy_for_kline("PFE") == "multifactor_score"


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


def test_research_strategies_exclude_mock_demo():
    from src.backtest.strategy_registry import research_strategy_ids

    assert research_strategy_ids() == (
        "event_baseline",
        "multifactor_score",
        "ml_probability",
    )


def test_mock_strategy_rejected_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import (
        StrategyPolicyError,
        validate_strategy_for_mode,
    )

    with pytest.raises(StrategyPolicyError, match="mock_multifactor_demo"):
        validate_strategy_for_mode(
            "mock_multifactor_demo",
            data_mode=BacktestMode.RESEARCH_GRADE,
        )


def test_mock_strategy_rejected_for_exploratory_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import (
        StrategyPolicyError,
        validate_strategy_for_mode,
    )

    with pytest.raises(StrategyPolicyError, match="requires data_mode='mock'"):
        validate_strategy_for_mode(
            "mock_multifactor_demo",
            data_mode=BacktestMode.EXPLORATORY,
        )


def test_mock_strategy_allowed_for_mock_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import validate_strategy_for_mode

    strategy = validate_strategy_for_mode(
        "mock_multifactor_demo",
        data_mode=BacktestMode.MOCK,
    )

    assert strategy.strategy_id == "mock_multifactor_demo"
    assert strategy.mock_only is True


def test_event_baseline_allowed_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import validate_strategy_for_mode

    strategy = validate_strategy_for_mode(
        "event_baseline",
        data_mode=BacktestMode.RESEARCH_GRADE,
    )

    assert strategy.strategy_id == "event_baseline"
    assert strategy.research_allowed is True


def test_all_research_strategy_ids_validate_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import (
        research_strategy_ids,
        validate_strategy_for_mode,
    )

    for strategy_id in research_strategy_ids():
        strategy = validate_strategy_for_mode(
            strategy_id,
            data_mode=BacktestMode.RESEARCH_GRADE,
        )

        assert strategy.strategy_id == strategy_id
        assert strategy.research_allowed is True


def test_non_research_strategy_rejected_for_research_grade_mode(monkeypatch):
    import src.backtest.strategy_registry as registry
    from src.backtest.data_sources import BacktestMode

    future_strategy = registry.StrategyDefinition(
        strategy_id="future_internal",
        display_name="Future Internal",
        research_allowed=False,
        mock_only=False,
    )
    strategies = getattr(registry, "_STRATEGIES", registry.STRATEGIES)
    monkeypatch.setitem(strategies, future_strategy.strategy_id, future_strategy)

    with pytest.raises(registry.StrategyPolicyError, match="future_internal"):
        registry.validate_strategy_for_mode(
            future_strategy.strategy_id,
            data_mode=BacktestMode.RESEARCH_GRADE,
        )


def test_public_strategies_cannot_be_mutated():
    from src.backtest.strategy_registry import STRATEGIES, StrategyDefinition

    accidental_strategy = StrategyDefinition(
        strategy_id="accidental_demo",
        display_name="Accidental Demo",
        research_allowed=False,
        mock_only=False,
    )

    with pytest.raises(TypeError):
        STRATEGIES[accidental_strategy.strategy_id] = accidental_strategy
