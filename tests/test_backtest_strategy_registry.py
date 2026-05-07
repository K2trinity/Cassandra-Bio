from __future__ import annotations

import pytest


def test_research_strategies_exclude_mock_demo():
    from src.backtest.strategy_registry import research_strategy_ids

    assert research_strategy_ids() == (
        "event_baseline",
        "multifactor_score",
        "ml_probability",
    )


def test_mock_strategy_rejected_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import StrategyPolicyError, validate_strategy_for_mode

    with pytest.raises(StrategyPolicyError, match="mock_multifactor_demo"):
        validate_strategy_for_mode(
            "mock_multifactor_demo",
            data_mode=BacktestMode.RESEARCH_GRADE,
        )


def test_event_baseline_allowed_for_research_grade_mode():
    from src.backtest.data_sources import BacktestMode
    from src.backtest.strategy_registry import validate_strategy_for_mode

    strategy = validate_strategy_for_mode(
        "event_baseline",
        data_mode=BacktestMode.RESEARCH_GRADE,
    )

    assert strategy.strategy_id == "event_baseline"
    assert strategy.research_allowed is True
