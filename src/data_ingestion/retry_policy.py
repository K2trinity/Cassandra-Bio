from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time

from src.data_ingestion.provider_result import ProviderResult


RETRYABLE_STATUSES = {"rate_limited", "retryable_error", "failed"}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_sleep_seconds: float = 1.0
    max_sleep_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_sleep_seconds < 0:
            raise ValueError("base_sleep_seconds must be non-negative")
        if self.max_sleep_seconds < 0:
            raise ValueError("max_sleep_seconds must be non-negative")


@dataclass(frozen=True)
class RetryOutcome:
    result: ProviderResult
    retry_count: int
    attempts: int
    sleep_seconds: tuple[float, ...]


def fetch_with_retry(
    fetch: Callable[[], ProviderResult],
    *,
    policy: RetryPolicy,
    sleeper: Callable[[float], None] | None = None,
) -> RetryOutcome:
    sleep = sleeper or time.sleep
    sleeps: list[float] = []
    attempts = 0
    result: ProviderResult | None = None

    while attempts < policy.max_attempts:
        attempts += 1
        result = fetch()
        if not should_retry_provider_result(result):
            break
        if attempts >= policy.max_attempts:
            break
        delay = _retry_sleep_seconds(
            result,
            retry_index=attempts - 1,
            policy=policy,
        )
        sleeps.append(delay)
        sleep(delay)

    if result is None:
        raise RuntimeError("provider fetch did not run")
    return RetryOutcome(
        result=result,
        retry_count=max(0, attempts - 1),
        attempts=attempts,
        sleep_seconds=tuple(sleeps),
    )


def should_retry_provider_result(result: ProviderResult) -> bool:
    if result.status not in RETRYABLE_STATUSES:
        return False
    if result.status != "failed":
        return True
    return _is_transient_failed_result(result)


def _is_transient_failed_result(result: ProviderResult) -> bool:
    message = str(result.message or "").lower()
    fatal_markers = (
        "400",
        "401",
        "402",
        "403",
        "404",
        "not found",
        "unauthorized",
        "forbidden",
        "fatal",
        "invalid api key",
    )
    return not any(marker in message for marker in fatal_markers)


def _retry_sleep_seconds(
    result: ProviderResult,
    *,
    retry_index: int,
    policy: RetryPolicy,
) -> float:
    if result.retry_after_seconds is not None:
        raw_delay = float(result.retry_after_seconds)
    else:
        raw_delay = policy.base_sleep_seconds * (2**retry_index)
    return max(0.0, min(raw_delay, policy.max_sleep_seconds))
