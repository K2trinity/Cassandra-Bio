from __future__ import annotations

import pytest


def test_fixed_window_rate_limit_allows_until_budget_exhausted():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limiter = FixedWindowRateLimit(max_requests=2, window_seconds=10)

    first = limiter.allow("tiingo", now=100.0)
    second = limiter.allow("tiingo", now=101.0)
    third = limiter.allow("tiingo", now=102.5)

    assert first.allowed is True
    assert first.retry_after_seconds == 0.0
    assert second.allowed is True
    assert second.retry_after_seconds == 0.0
    assert third.allowed is False
    assert third.retry_after_seconds == 7.5


def test_fixed_window_rate_limit_scopes_provider_windows_independently():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limiter = FixedWindowRateLimit(max_requests=1, window_seconds=5)

    assert limiter.allow("tiingo", now=10.0).allowed is True
    tiingo_limited = limiter.allow("tiingo", now=11.0)
    fmp_decision = limiter.allow("fmp", now=11.0)

    assert tiingo_limited.allowed is False
    assert tiingo_limited.retry_after_seconds == 4.0
    assert fmp_decision.allowed is True
    assert fmp_decision.retry_after_seconds == 0.0


def test_fixed_window_rate_limit_resets_after_window_elapsed():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limiter = FixedWindowRateLimit(max_requests=1, window_seconds=5)

    assert limiter.allow("sec", now=10.0).allowed is True
    assert limiter.allow("sec", now=14.0).allowed is False

    reset_decision = limiter.allow("sec", now=15.0)

    assert reset_decision.allowed is True
    assert reset_decision.retry_after_seconds == 0.0


@pytest.mark.parametrize(
    ("max_requests", "window_seconds"),
    [
        (0, 10),
        (1, 0),
        (-1, 10),
        (1, -0.1),
    ],
)
def test_fixed_window_rate_limit_validates_positive_budget(
    max_requests: int, window_seconds: float
):
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    with pytest.raises(ValueError):
        FixedWindowRateLimit(max_requests=max_requests, window_seconds=window_seconds)


def test_fixed_window_rate_limit_validates_non_empty_provider():
    from src.data_ingestion.rate_limit import FixedWindowRateLimit

    limiter = FixedWindowRateLimit(max_requests=1, window_seconds=5)

    with pytest.raises(ValueError, match="provider"):
        limiter.allow("  ", now=10.0)
