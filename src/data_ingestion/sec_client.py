from __future__ import annotations

from typing import Any

from src.data_ingestion.http_client import (
    RequestsHttpClient,
    build_request_hash,
    classify_http_status,
    retry_after_seconds,
)
from src.data_ingestion.provider_result import ProviderResult

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class SecClient:
    def __init__(self, user_agent: str, http_client: Any | None = None) -> None:
        self.user_agent = str(user_agent).strip()
        if not self.user_agent:
            raise ValueError("user_agent must be non-empty")
        self.http_client = http_client or RequestsHttpClient()

    def fetch_companyfacts(self, cik: str | int) -> ProviderResult:
        return self._fetch(SEC_COMPANYFACTS_URL, cik)

    def fetch_submissions(self, cik: str | int) -> ProviderResult:
        return self._fetch(SEC_SUBMISSIONS_URL, cik)

    def _fetch(self, url_template: str, cik: str | int) -> ProviderResult:
        padded_cik = _padded_cik(cik)
        url = url_template.format(cik=padded_cik)
        request_hash = build_request_hash(method="GET", url=url)
        response = self.http_client.get(url, params=None, headers=self._headers())
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

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }


def _padded_cik(value: str | int) -> str:
    digits = "".join(char for char in str(value).strip() if char.isdigit())
    if not digits:
        raise ValueError("CIK must contain digits")
    if len(digits) > 10:
        raise ValueError("CIK must be at most 10 digits")
    return digits.zfill(10)
