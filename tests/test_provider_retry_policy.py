from __future__ import annotations

from src.data_ingestion.provider_result import ProviderResult
from src.data_ingestion.retry_policy import RetryPolicy, fetch_with_retry


def test_retry_policy_honors_retry_after_and_caps_sleep() -> None:
    results = iter(
        [
            ProviderResult(
                status="rate_limited",
                request_hash="req_one",
                retry_after_seconds=10,
            ),
            ProviderResult(status="success", request_hash="req_two", rows=[]),
        ]
    )
    sleeps: list[float] = []

    outcome = fetch_with_retry(
        lambda: next(results),
        policy=RetryPolicy(max_attempts=3, max_sleep_seconds=2.5),
        sleeper=sleeps.append,
    )

    assert outcome.result.status == "success"
    assert outcome.retry_count == 1
    assert outcome.attempts == 2
    assert sleeps == [2.5]
    assert outcome.sleep_seconds == (2.5,)


def test_retry_policy_uses_bounded_exponential_backoff() -> None:
    attempts = [
        ProviderResult(status="retryable_error", request_hash="req_one"),
        ProviderResult(status="failed", request_hash="req_two", message="timeout"),
        ProviderResult(status="success", request_hash="req_three", rows=[]),
    ]
    sleeps: list[float] = []

    outcome = fetch_with_retry(
        lambda: attempts.pop(0),
        policy=RetryPolicy(
            max_attempts=4,
            base_sleep_seconds=1.5,
            max_sleep_seconds=2.0,
        ),
        sleeper=sleeps.append,
    )

    assert outcome.result.request_hash == "req_three"
    assert outcome.retry_count == 2
    assert sleeps == [1.5, 2.0]


def test_retry_policy_does_not_retry_fatal_failed_result() -> None:
    calls = 0

    def fetch() -> ProviderResult:
        nonlocal calls
        calls += 1
        return ProviderResult(
            status="failed",
            request_hash="req_fatal",
            message="fatal provider validation error",
        )

    outcome = fetch_with_retry(
        fetch,
        policy=RetryPolicy(max_attempts=3, max_sleep_seconds=0),
        sleeper=lambda _: None,
    )

    assert outcome.result.status == "failed"
    assert outcome.retry_count == 0
    assert calls == 1
