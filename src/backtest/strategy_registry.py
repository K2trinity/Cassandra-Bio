from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from src.backtest.data_sources import BacktestMode
from src.backtest.mock_dataset import MOCK_DATA_MODE, MOCK_SCOPE

EVENT_BASELINE: Final[str] = "event_baseline"
MOCK_MULTIFACTOR_DEMO: Final[str] = "mock_multifactor_demo"
MULTIFACTOR_SCORE: Final[str] = "multifactor_score"
ML_PROBABILITY: Final[str] = "ml_probability"


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    display_name: str
    research_allowed: bool
    mock_only: bool


@dataclass(frozen=True)
class StrategyContext:
    strategy_id: str
    data_mode: str
    mock_scope: str | None


class StrategyPolicyError(ValueError):
    pass


class StrategyAccessError(StrategyPolicyError):
    """Raised when a strategy is not valid for the requested data mode."""


_STRATEGIES: dict[str, StrategyDefinition] = {
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
STRATEGIES: Mapping[str, StrategyDefinition] = MappingProxyType(_STRATEGIES)
KNOWN_STRATEGIES: Final[frozenset[str]] = frozenset(_STRATEGIES)


def default_strategy_for_kline(ticker: object) -> str:
    return MULTIFACTOR_SCORE


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
    if strategy_id not in _STRATEGIES:
        raise StrategyPolicyError(f"unknown strategy: {strategy_id}")

    definition = _STRATEGIES[strategy_id]
    resolved_mode = BacktestMode(data_mode)

    if resolved_mode == BacktestMode.RESEARCH_GRADE and definition.mock_only:
        raise StrategyPolicyError(
            f"{strategy_id} is mock-only and cannot run in research-grade mode"
        )

    if resolved_mode == BacktestMode.RESEARCH_GRADE and not definition.research_allowed:
        raise StrategyPolicyError(
            f"{strategy_id} is not allowed in research-grade mode"
        )

    if definition.mock_only and resolved_mode != BacktestMode.MOCK:
        raise StrategyPolicyError(f"{strategy_id} requires data_mode='mock'")

    return definition


def validate_strategy_access(
    strategy_id: str,
    data_mode: str,
    mock_scope: str | None,
) -> None:
    if strategy_id not in _STRATEGIES:
        raise StrategyAccessError(f"unknown strategy: {strategy_id}")

    if strategy_id != MOCK_MULTIFACTOR_DEMO:
        validate_strategy_for_mode(strategy_id, data_mode=BacktestMode.EXPLORATORY)
        return

    if data_mode != MOCK_DATA_MODE:
        raise StrategyAccessError("mock_multifactor_demo requires data_mode='mock'")
    if mock_scope != MOCK_SCOPE:
        raise StrategyAccessError(
            "mock_multifactor_demo requires mock_scope='biotech_mock_v1'"
        )

    validate_strategy_for_mode(strategy_id, data_mode=BacktestMode.MOCK)
