from __future__ import annotations

from typing import Any

from src.data_ingestion.http_client import (
    RequestsHttpClient,
    build_request_hash,
    classify_http_status,
    retry_after_seconds,
)
from src.data_ingestion.provider_result import ProviderResult

FMP_BASE_URL = "https://financialmodelingprep.com/stable"


class FmpClient:
    def __init__(self, api_key: str, http_client: Any | None = None) -> None:
        self.api_key = api_key
        self.http_client = http_client or RequestsHttpClient()

    def fetch_profile(self, ticker: str) -> ProviderResult:
        return self._fetch("profile", params={"symbol": _ticker(ticker)})

    def fetch_income_statement(
        self,
        ticker: str,
        period: str = "quarter",
    ) -> ProviderResult:
        return self._fetch(
            "income-statement",
            params={"symbol": _ticker(ticker), "period": period},
        )

    def fetch_balance_sheet(
        self,
        ticker: str,
        period: str = "quarter",
    ) -> ProviderResult:
        return self._fetch(
            "balance-sheet-statement",
            params={"symbol": _ticker(ticker), "period": period},
        )

    def fetch_cash_flow(
        self,
        ticker: str,
        period: str = "quarter",
    ) -> ProviderResult:
        return self._fetch(
            "cash-flow-statement",
            params={"symbol": _ticker(ticker), "period": period},
        )

    def _fetch(self, path: str, *, params: dict[str, Any]) -> ProviderResult:
        url = f"{FMP_BASE_URL}/{path}"
        request_params = {**params, "apikey": self.api_key}
        request_hash = build_request_hash(
            method="GET",
            url=url,
            params=request_params,
        )
        response = self.http_client.get(url, params=request_params, headers=None)
        status = classify_http_status(response.status_code)
        if status == "success":
            try:
                payload = response.json()
            except ValueError:
                return ProviderResult(
                    status="fatal_error",
                    request_hash=request_hash,
                    message="invalid JSON response",
                )
            return ProviderResult(
                status=status,
                request_hash=request_hash,
                payload=payload,
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
