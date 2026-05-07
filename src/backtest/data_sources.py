from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BiasProfile(StrEnum):
    SURVIVORSHIP_BIAS_FREE = "survivorship_bias_free"
    SURVIVORSHIP_BIASED = "survivorship_biased"
    UNKNOWN_BIAS = "unknown_bias"
    MOCK = "mock"


class BacktestMode(StrEnum):
    EXPLORATORY = "exploratory"
    RESEARCH_GRADE = "research_grade"
    MOCK = "mock"


@dataclass(frozen=True)
class SourceProfile:
    source_id: str
    display_name: str
    bias_profile: BiasProfile
    supports_delisted: bool
    supports_point_in_time_universe: bool
    supports_delisting_returns: bool


@dataclass(frozen=True)
class SourceValidation:
    allowed: bool
    bias_profile: BiasProfile
    bias_warnings: list[str]


class SourcePolicyError(ValueError):
    pass


YFINANCE_PROFILE = SourceProfile(
    source_id="yfinance",
    display_name="Yahoo Finance via yfinance",
    bias_profile=BiasProfile.SURVIVORSHIP_BIASED,
    supports_delisted=False,
    supports_point_in_time_universe=False,
    supports_delisting_returns=False,
)


def validate_source_for_mode(
    profile: SourceProfile,
    mode: BacktestMode | str,
) -> SourceValidation:
    resolved_mode = BacktestMode(mode)
    warnings = _warnings_for(profile)

    if resolved_mode == BacktestMode.MOCK:
        return SourceValidation(
            allowed=True,
            bias_profile=BiasProfile.MOCK,
            bias_warnings=[],
        )

    if (
        resolved_mode == BacktestMode.RESEARCH_GRADE
        and profile.bias_profile != BiasProfile.SURVIVORSHIP_BIAS_FREE
    ):
        raise SourcePolicyError(
            f"Source {profile.source_id} cannot be used for research-grade "
            "backtests because it is not survivorship-bias-free."
        )

    return SourceValidation(
        allowed=True,
        bias_profile=profile.bias_profile,
        bias_warnings=warnings,
    )


def _warnings_for(profile: SourceProfile) -> list[str]:
    if profile.bias_profile == BiasProfile.SURVIVORSHIP_BIASED:
        return [
            f"Source {profile.source_id} is survivorship-biased and is not research-grade."
        ]
    if profile.bias_profile == BiasProfile.UNKNOWN_BIAS:
        return [
            f"Source {profile.source_id} has unknown survivorship-bias coverage."
        ]
    return []
