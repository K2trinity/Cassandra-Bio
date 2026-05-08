from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderResult:
    status: str
    request_hash: str
    payload: Any | None = None
    rows: list[dict[str, Any]] | None = None
    message: str | None = None
    retry_after_seconds: float | None = None
