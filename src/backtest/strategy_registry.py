from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.backtest.mock_dataset import MOCK_DATA_MODE, MOCK_SCOPE

EVENT_BASELINE: Final[str] = "event_baseline"
MOCK_MULTIFACTOR_DEMO: Final[str] = "mock_multifactor_demo"
MULTIFACTOR_SCORE: Final[str] = "multifactor_score"
ML_PROBABILITY: Final[str] = "ml_probability"

KNOWN_STRATEGIES: Final[set[str]] = {
    EVENT_BASELINE,
    MOCK_MULTIFACTOR_DEMO,
    MULTIFACTOR_SCORE,
    ML_PROBABILITY,
}


class StrategyAccessError(ValueError):
    """Raised when a strategy is not valid for the requested data mode."""


@dataclass(frozen=True)
class StrategyContext:
    strategy_id: str
    data_mode: str
    mock_scope: str | None


def default_strategy_for_kline(ticker: object) -> str:
    return MULTIFACTOR_SCORE


def validate_strategy_access(
    strategy_id: str,
    data_mode: str,
    mock_scope: str | None,
) -> None:
    if strategy_id not in KNOWN_STRATEGIES:
        raise StrategyAccessError(f"unknown strategy: {strategy_id}")

    if strategy_id != MOCK_MULTIFACTOR_DEMO:
        return

    if data_mode != MOCK_DATA_MODE:
        raise StrategyAccessError(
            "mock_multifactor_demo requires data_mode='mock'"
        )
    if mock_scope != MOCK_SCOPE:
        raise StrategyAccessError(
            "mock_multifactor_demo requires mock_scope='biotech_mock_v1'"
        )
