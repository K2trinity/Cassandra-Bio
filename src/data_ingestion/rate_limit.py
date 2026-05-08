from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float


@dataclass
class _ProviderWindow:
    started_at: float
    request_count: int


class FixedWindowRateLimit:
    """Deterministic fixed-window request budget keyed by provider."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self._windows: dict[str, _ProviderWindow] = {}

    def allow(self, provider: str, *, now: float | None = None) -> RateLimitDecision:
        provider_key = _normalize_provider(provider)
        current_time = float(time.monotonic() if now is None else now)
        window = self._windows.get(provider_key)

        if (
            window is None
            or current_time - window.started_at >= self.window_seconds
        ):
            self._windows[provider_key] = _ProviderWindow(
                started_at=current_time,
                request_count=1,
            )
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        if window.request_count < self.max_requests:
            window.request_count += 1
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        retry_after = max(
            0.0,
            (window.started_at + self.window_seconds) - current_time,
        )
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=retry_after,
        )


def _normalize_provider(provider: str) -> str:
    provider_key = str(provider).strip().lower()
    if not provider_key:
        raise ValueError("provider must be non-empty")
    return provider_key
