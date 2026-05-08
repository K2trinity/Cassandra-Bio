from __future__ import annotations


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
