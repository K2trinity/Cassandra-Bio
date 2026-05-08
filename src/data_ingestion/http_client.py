from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

SECRET_QUERY_KEYS = frozenset({"token", "apikey", "api_key", "access_key"})


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON response") from exc


class RequestsHttpClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        response = self._session.get(
            url,
            params=dict(params or {}),
            headers=dict(headers or {}),
            timeout=self.timeout_seconds,
        )
        return HttpResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )


def build_request_hash(
    *,
    method: str,
    url: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    safe_params = {
        str(key): str(value)
        for key, value in dict(params or {}).items()
        if str(key).lower() not in SECRET_QUERY_KEYS
    }
    payload = {
        "method": str(method).upper(),
        "url": _url_without_query(url),
        "params": dict(sorted(safe_params.items())),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"req_{digest}"


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SECRET_QUERY_KEYS:
            query.append((key, "<redacted>"))
        else:
            query.append((key, value))
    redacted_query = urlencode(query, safe="<>")
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment)
    )


def classify_http_status(status_code: int) -> str:
    normalized = int(status_code)
    if 200 <= normalized < 300:
        return "success"
    if normalized == 404:
        return "not_found"
    if normalized == 429:
        return "rate_limited"
    if 500 <= normalized < 600:
        return "retryable_error"
    return "fatal_error"


def _url_without_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
