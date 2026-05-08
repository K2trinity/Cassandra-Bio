from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.data_ingestion.http_client import (
    RequestsHttpClient,
    build_request_hash,
    classify_http_status,
)

TIINGO_DAILY_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


@dataclass(frozen=True)
class ProviderResult:
    status: str
    request_hash: str
    payload: Any | None = None
    rows: list[dict[str, Any]] | None = None
    message: str | None = None
    retry_after_seconds: float | None = None


class TiingoClient:
    def __init__(self, api_key: str, http_client: Any | None = None) -> None:
        self.api_key = api_key
        self.http_client = http_client or RequestsHttpClient()

    def fetch_daily_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        symbol = _ticker(ticker)
        url = TIINGO_DAILY_URL.format(ticker=symbol)
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "resampleFreq": "daily",
        }
        request_hash = build_request_hash(method="GET", url=url, params=params)
        response = self.http_client.get(
            url,
            params=params,
            headers={"Authorization": f"Token {self.api_key}"},
        )
        status = classify_http_status(response.status_code)
        if status == "success":
            return ProviderResult(
                status=status,
                request_hash=request_hash,
                rows=response.json(),
            )
        return ProviderResult(
            status=status,
            request_hash=request_hash,
            message=f"HTTP {response.status_code}",
            retry_after_seconds=_retry_after_seconds(response.headers),
        )


def _ticker(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("ticker must be non-empty")
    return text


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    for key, value in headers.items():
        if key.lower() != "retry-after":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
