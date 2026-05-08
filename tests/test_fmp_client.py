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
    assert fake.calls[0][0].endswith("/profile/MRNA")
    assert fake.calls[0][1] == {"apikey": "unit-test-fmp-key"}
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
        "https://financialmodelingprep.com/api/v3/income-statement/MRNA",
        "https://financialmodelingprep.com/api/v3/balance-sheet-statement/MRNA",
        "https://financialmodelingprep.com/api/v3/cash-flow-statement/MRNA",
    ]
    assert all(
        params == {"period": "quarter", "apikey": "unit-test-fmp-key"}
        for _, params, _ in fake.calls
    )
