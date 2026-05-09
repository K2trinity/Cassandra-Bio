from __future__ import annotations

from typing import Any

from src.data_ingestion.http_client import (
    RequestsHttpClient,
    build_request_hash,
    classify_http_status,
    retry_after_seconds,
)
from src.data_ingestion.provider_result import ProviderResult

TIINGO_DAILY_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


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
            try:
                rows = response.json()
            except ValueError:
                return ProviderResult(
                    status="fatal_error",
                    request_hash=request_hash,
                    message="invalid JSON response",
                )
            return ProviderResult(
                status=status,
                request_hash=request_hash,
                rows=rows,
            )
        return ProviderResult(
            status=status,
            request_hash=request_hash,
            message=f"HTTP {response.status_code}",
            retry_after_seconds=retry_after_seconds(response.headers),
        )


def _ticker(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("ticker must be non-empty")
    return text
