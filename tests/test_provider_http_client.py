from __future__ import annotations

import pytest
import requests


def test_build_request_hash_is_deterministic_and_ignores_secret_params():
    from src.data_ingestion.http_client import build_request_hash

    first = build_request_hash(
        method="GET",
        url="https://api.tiingo.com/tiingo/daily/MRNA/prices",
        params={"token": "secret", "startDate": "2020-01-01", "endDate": "2020-01-31"},
    )
    second = build_request_hash(
        method="get",
        url="https://api.tiingo.com/tiingo/daily/MRNA/prices",
        params={"endDate": "2020-01-31", "startDate": "2020-01-01", "token": "other"},
    )

    assert first == second
    assert first.startswith("req_")


def test_build_request_hash_includes_non_secret_url_query_params():
    from src.data_ingestion.http_client import build_request_hash

    mrna = build_request_hash(
        method="GET",
        url="https://example.test/prices?symbol=MRNA",
        params={"startDate": "2020-01-01"},
    )
    jnj = build_request_hash(
        method="GET",
        url="https://example.test/prices?symbol=JNJ",
        params={"startDate": "2020-01-01"},
    )

    assert mrna != jnj


def test_build_request_hash_ignores_secret_url_query_values():
    from src.data_ingestion.http_client import build_request_hash

    first = build_request_hash(
        method="GET",
        url="https://example.test/prices?symbol=MRNA&token=secret",
        params={"apikey": "first"},
    )
    second = build_request_hash(
        method="GET",
        url="https://example.test/prices?token=other&symbol=MRNA",
        params={"apikey": "second"},
    )

    assert first == second


def test_redact_url_removes_token_and_apikey_query_values():
    from src.data_ingestion.http_client import redact_url

    redacted = redact_url("https://example.test/path?token=abc&apikey=def&symbol=MRNA")

    assert "abc" not in redacted
    assert "def" not in redacted
    assert "token=<redacted>" in redacted
    assert "apikey=<redacted>" in redacted
    assert "symbol=MRNA" in redacted


def test_redact_url_redacts_malformed_url_best_effort():
    from src.data_ingestion.http_client import redact_url

    redacted = redact_url("http://[bad?token=secret&symbol=MRNA")

    assert "secret" not in redacted
    assert "token=<redacted>" in redacted
    assert "symbol=MRNA" in redacted


def test_requests_http_client_redacts_request_exception_context(monkeypatch):
    from src.data_ingestion.http_client import ProviderHttpError, RequestsHttpClient

    class FakeSession:
        def get(self, url, *, params, headers, timeout):
            raise requests.RequestException(
                f"failed url={url}?token=secret params={params}"
            )

    client = RequestsHttpClient()
    monkeypatch.setattr(client, "_session", FakeSession())

    with pytest.raises(ProviderHttpError) as exc_info:
        client.get(
            "https://example.test/prices",
            params={"token": "secret", "symbol": "MRNA"},
        )

    message = str(exc_info.value)
    assert "secret" not in message
    assert "token=<redacted>" in message
    assert "symbol=MRNA" in message


def test_response_helpers_classify_common_http_statuses():
    from src.data_ingestion.http_client import classify_http_status

    assert classify_http_status(200) == "success"
    assert classify_http_status(404) == "not_found"
    assert classify_http_status(429) == "rate_limited"
    assert classify_http_status(500) == "retryable_error"
    assert classify_http_status(401) == "fatal_error"


def test_retry_after_seconds_parses_numeric_and_http_date():
    from src.data_ingestion.http_client import retry_after_seconds

    assert retry_after_seconds({"Retry-After": "12"}) == 12.0
    assert retry_after_seconds(
        {"Retry-After": "Wed, 21 Oct 2030 07:28:00 GMT"},
        now="Wed, 21 Oct 2030 07:27:30 GMT",
    ) == 30.0


def test_fake_response_json_raises_clear_error_for_invalid_json():
    from src.data_ingestion.http_client import HttpResponse

    response = HttpResponse(status_code=200, text="not-json", headers={})

    with pytest.raises(ValueError, match="invalid JSON response"):
        response.json()
