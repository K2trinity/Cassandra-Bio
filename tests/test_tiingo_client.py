from __future__ import annotations


class FakeHttp:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = '[{"date":"2026-05-01T00:00:00.000Z"}]',
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


def test_tiingo_client_uses_authorization_header_and_safe_request_hash():
    from src.data_ingestion.tiingo_client import TiingoClient

    fake = FakeHttp()
    client = TiingoClient(api_key="unit-test-tiingo-token", http_client=fake)

    result = client.fetch_daily_prices(
        ticker="mrna",
        start_date="2026-05-01",
        end_date="2026-05-08",
    )

    assert result.status == "success"
    assert result.rows == [{"date": "2026-05-01T00:00:00.000Z"}]
    assert result.request_hash.startswith("req_")
    url, params, headers = fake.calls[0]
    assert url.endswith("/tiingo/daily/MRNA/prices")
    assert params == {
        "startDate": "2026-05-01",
        "endDate": "2026-05-08",
        "resampleFreq": "daily",
    }
    assert headers["Authorization"] == "Token unit-test-tiingo-token"
    assert "unit-test-tiingo-token" not in result.request_hash


def test_tiingo_client_preserves_retry_after_for_rate_limits():
    from src.data_ingestion.tiingo_client import TiingoClient

    fake = FakeHttp(status_code=429, text='{"detail":"slow down"}', headers={"Retry-After": "12"})
    client = TiingoClient(api_key="unit-test-tiingo-token", http_client=fake)

    result = client.fetch_daily_prices("MRNA", "2026-05-01", "2026-05-08")

    assert result.status == "rate_limited"
    assert result.rows is None
    assert result.retry_after_seconds == 12.0
    assert result.message == "HTTP 429"


def test_tiingo_client_returns_fatal_error_for_invalid_json_success_response():
    from src.data_ingestion.tiingo_client import TiingoClient

    fake = FakeHttp(status_code=200, text="not-json")
    client = TiingoClient(api_key="unit-test-tiingo-token", http_client=fake)

    result = client.fetch_daily_prices("MRNA", "2026-05-01", "2026-05-08")

    assert result.status == "fatal_error"
    assert result.rows is None
    assert result.message == "invalid JSON response"
