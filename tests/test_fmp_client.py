from __future__ import annotations


class FakeHttp:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = '[{"symbol":"MRNA","industry":"Biotechnology"}]',
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


def test_fmp_client_uses_apikey_param_but_request_hash_excludes_secret():
    from src.data_ingestion.fmp_client import FmpClient

    fake = FakeHttp()
    client = FmpClient(api_key="unit-test-fmp-key", http_client=fake)

    result = client.fetch_profile("mrna")

    assert result.status == "success"
    assert result.payload == [{"symbol": "MRNA", "industry": "Biotechnology"}]
    assert fake.calls[0][0] == "https://financialmodelingprep.com/stable/profile"
    assert fake.calls[0][1] == {"symbol": "MRNA", "apikey": "unit-test-fmp-key"}
    assert "unit-test-fmp-key" not in result.request_hash


def test_fmp_statement_methods_use_quarter_period_by_default():
    from src.data_ingestion.fmp_client import FmpClient

    fake = FakeHttp(text='[{"calendarYear":"2026"}]')
    client = FmpClient(api_key="unit-test-fmp-key", http_client=fake)

    income = client.fetch_income_statement("MRNA")
    balance = client.fetch_balance_sheet("MRNA")
    cash_flow = client.fetch_cash_flow("MRNA")

    assert income.status == "success"
    assert balance.status == "success"
    assert cash_flow.status == "success"
    assert [call[0] for call in fake.calls] == [
        "https://financialmodelingprep.com/stable/income-statement",
        "https://financialmodelingprep.com/stable/balance-sheet-statement",
        "https://financialmodelingprep.com/stable/cash-flow-statement",
    ]
    assert all(
        params == {"symbol": "MRNA", "period": "quarter", "apikey": "unit-test-fmp-key"}
        for _, params, _ in fake.calls
    )


def test_fmp_client_returns_fatal_error_for_invalid_json_success_response():
    from src.data_ingestion.fmp_client import FmpClient

    fake = FakeHttp(status_code=200, text="not-json")
    client = FmpClient(api_key="unit-test-fmp-key", http_client=fake)

    result = client.fetch_profile("MRNA")

    assert result.status == "fatal_error"
    assert result.payload is None
    assert result.message == "invalid JSON response"


def test_fmp_client_preserves_retry_after_for_rate_limits():
    from src.data_ingestion.fmp_client import FmpClient

    fake = FakeHttp(status_code=429, text='{"message":"slow down"}', headers={"Retry-After": "18"})
    client = FmpClient(api_key="unit-test-fmp-key", http_client=fake)

    result = client.fetch_profile("MRNA")

    assert result.status == "rate_limited"
    assert result.payload is None
    assert result.retry_after_seconds == 18.0
    assert result.message == "HTTP 429"
