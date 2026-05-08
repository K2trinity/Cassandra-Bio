from __future__ import annotations

import pytest


class FakeHttp:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = '{"facts":{}}',
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        from src.data_ingestion.http_client import HttpResponse

        self.calls.append((url, params, headers))
        return HttpResponse(
            status_code=self.status_code,
            text=self.text,
            headers=self.headers,
        )


def test_sec_client_zero_pads_cik_and_sends_user_agent():
    from src.data_ingestion.sec_client import SecClient

    fake = FakeHttp()
    client = SecClient(user_agent="CassandraBio unit-test-agent", http_client=fake)

    result = client.fetch_companyfacts(cik="1682852")

    assert result.status == "success"
    assert fake.calls[0][0].endswith("/api/xbrl/companyfacts/CIK0001682852.json")
    assert fake.calls[0][2]["User-Agent"] == "CassandraBio unit-test-agent"
    assert fake.calls[0][2]["Accept-Encoding"] == "gzip, deflate"
    assert fake.calls[0][2]["Host"] == "data.sec.gov"
    assert result.payload == {"facts": {}}


def test_sec_client_fetches_submissions_payload():
    from src.data_ingestion.sec_client import SecClient

    fake = FakeHttp(text='{"cik":"0001682852"}')
    client = SecClient(user_agent="CassandraBio unit-test-agent", http_client=fake)

    result = client.fetch_submissions(cik=1682852)

    assert result.status == "success"
    assert fake.calls[0][0].endswith("/submissions/CIK0001682852.json")
    assert result.payload == {"cik": "0001682852"}


def test_sec_client_returns_fatal_error_for_invalid_json_success_response():
    from src.data_ingestion.sec_client import SecClient

    fake = FakeHttp(status_code=200, text="not-json")
    client = SecClient(user_agent="CassandraBio unit-test-agent", http_client=fake)

    result = client.fetch_companyfacts(cik="1682852")

    assert result.status == "fatal_error"
    assert result.payload is None
    assert result.message == "invalid JSON response"


def test_sec_client_preserves_retry_after_for_rate_limits():
    from src.data_ingestion.sec_client import SecClient

    fake = FakeHttp(status_code=429, text='{"message":"slow down"}', headers={"Retry-After": "15"})
    client = SecClient(user_agent="CassandraBio unit-test-agent", http_client=fake)

    result = client.fetch_companyfacts(cik="1682852")

    assert result.status == "rate_limited"
    assert result.payload is None
    assert result.retry_after_seconds == 15.0
    assert result.message == "HTTP 429"


def test_sec_client_rejects_empty_user_agent():
    from src.data_ingestion.sec_client import SecClient

    with pytest.raises(ValueError, match="user_agent must be non-empty"):
        SecClient(user_agent="  ")


def test_sec_client_rejects_overlong_cik_digit_strings():
    from src.data_ingestion.sec_client import SecClient

    client = SecClient(user_agent="CassandraBio unit-test-agent", http_client=FakeHttp())

    with pytest.raises(ValueError, match="CIK must be at most 10 digits"):
        client.fetch_companyfacts(cik="12345678901")
