from __future__ import annotations

from dataclasses import dataclass

from src.backtest.data_sources import BacktestMode

EVENT_BASELINE = "event_baseline"
MULTIFACTOR_SCORE = "multifactor_score"
MOCK_MULTIFACTOR_DEMO = "mock_multifactor_demo"
ML_PROBABILITY = "ml_probability"


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    display_name: str
    research_allowed: bool
    mock_only: bool


class StrategyPolicyError(ValueError):
    pass


STRATEGIES: dict[str, StrategyDefinition] = {
    EVENT_BASELINE: StrategyDefinition(
        strategy_id=EVENT_BASELINE,
        display_name="Event Baseline",
        research_allowed=True,
        mock_only=False,
    ),
    MULTIFACTOR_SCORE: StrategyDefinition(
        strategy_id=MULTIFACTOR_SCORE,
        display_name="Multifactor Score",
        research_allowed=True,
        mock_only=False,
    ),
    MOCK_MULTIFACTOR_DEMO: StrategyDefinition(
        strategy_id=MOCK_MULTIFACTOR_DEMO,
        display_name="Mock Multifactor Demo",
        research_allowed=False,
        mock_only=True,
    ),
    ML_PROBABILITY: StrategyDefinition(
        strategy_id=ML_PROBABILITY,
        display_name="ML Probability",
        research_allowed=True,
        mock_only=False,
    ),
}


def research_strategy_ids() -> tuple[str, ...]:
    return tuple(
        strategy_id
        for strategy_id, definition in STRATEGIES.items()
        if definition.research_allowed
    )


def validate_strategy_for_mode(
    strategy_id: str,
    *,
    data_mode: BacktestMode | str,
) -> StrategyDefinition:
    if strategy_id not in STRATEGIES:
        raise StrategyPolicyError(f"unknown strategy: {strategy_id}")

    definition = STRATEGIES[strategy_id]
    resolved_mode = BacktestMode(data_mode)

    if resolved_mode == BacktestMode.RESEARCH_GRADE and definition.mock_only:
        raise StrategyPolicyError(
            f"{strategy_id} is mock-only and cannot run in research-grade mode"
        )

    if definition.mock_only and resolved_mode != BacktestMode.MOCK:
        raise StrategyPolicyError(
            f"{strategy_id} requires data_mode='mock'"
        )

    return definition
