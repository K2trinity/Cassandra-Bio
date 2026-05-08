from __future__ import annotations

import pytest


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


def test_redact_url_removes_token_and_apikey_query_values():
    from src.data_ingestion.http_client import redact_url

    redacted = redact_url("https://example.test/path?token=abc&apikey=def&symbol=MRNA")

    assert "abc" not in redacted
    assert "def" not in redacted
    assert "token=<redacted>" in redacted
    assert "apikey=<redacted>" in redacted
    assert "symbol=MRNA" in redacted


def test_response_helpers_classify_common_http_statuses():
    from src.data_ingestion.http_client import classify_http_status

    assert classify_http_status(200) == "success"
    assert classify_http_status(404) == "not_found"
    assert classify_http_status(429) == "rate_limited"
    assert classify_http_status(500) == "retryable_error"
    assert classify_http_status(401) == "fatal_error"


def test_fake_response_json_raises_clear_error_for_invalid_json():
    from src.data_ingestion.http_client import HttpResponse

    response = HttpResponse(status_code=200, text="not-json", headers={})

    with pytest.raises(ValueError, match="invalid JSON response"):
        response.json()
