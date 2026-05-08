from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

SECRET_QUERY_KEYS = frozenset({"token", "apikey", "api_key", "access_key"})
_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:token|apikey|api_key|access_key)=)([^&#\s]*)"
)


class ProviderHttpError(RuntimeError):
    """Raised when provider HTTP requests fail before a response is available."""


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
        try:
            response = self._session.get(
                url,
                params=dict(params or {}),
                headers=dict(headers or {}),
                timeout=self.timeout_seconds,
            )
        except (requests.RequestException, URLError) as exc:
            safe_url = redact_url(_url_with_params(url, params))
            raise ProviderHttpError(
                f"GET request failed for {safe_url}: {exc.__class__.__name__}"
            ) from None
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
    safe_params = _safe_query_pairs_from_url(url) + _safe_param_pairs(params)
    payload = {
        "method": str(method).upper(),
        "url": _url_without_query(url),
        "params": sorted(safe_params),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"req_{digest}"


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return _redact_secret_query_text(str(url))
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
    try:
        parts = urlsplit(url)
    except ValueError:
        return str(url).split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _safe_query_pairs_from_url(url: str) -> list[tuple[str, str]]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return []
    return _filter_safe_pairs(parse_qsl(parts.query, keep_blank_values=True))


def _safe_param_pairs(params: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    return _filter_safe_pairs(_iter_param_pairs(params))


def _filter_safe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (key, value)
        for key, value in pairs
        if str(key).lower() not in SECRET_QUERY_KEYS
    ]


def _iter_param_pairs(params: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    if not params:
        return []
    pairs = []
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            pairs.extend((str(key), str(item)) for item in value)
        else:
            pairs.append((str(key), str(value)))
    return pairs


def _url_with_params(url: str, params: Mapping[str, Any] | None) -> str:
    param_pairs = _iter_param_pairs(params)
    if not param_pairs:
        return url

    encoded_params = urlencode(param_pairs, doseq=True)
    try:
        parts = urlsplit(url)
    except ValueError:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{encoded_params}"

    query = parts.query
    if query:
        query = f"{query}&{encoded_params}"
    else:
        query = encoded_params
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _redact_secret_query_text(text: str) -> str:
    return _SECRET_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>", text)
