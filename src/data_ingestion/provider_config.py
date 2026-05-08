from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping

PROVIDER_ENV_KEYS = {
    "tiingo": "TIINGO_API_KEY",
    "fmp": "FMP_API_KEY",
    "sec": "SEC_USER_AGENT",
}

PROVIDERS_WITHOUT_CREDENTIALS = frozenset({"nasdaq", "nasdaq_trader"})


@dataclass(frozen=True)
class ProviderConfig:
    tiingo_api_key: str | None = None
    fmp_api_key: str | None = None
    sec_user_agent: str | None = None

    def __repr__(self) -> str:
        return (
            "ProviderConfig("
            f"tiingo_api_key={_presence(self.tiingo_api_key)}, "
            f"fmp_api_key={_presence(self.fmp_api_key)}, "
            f"sec_user_agent={_presence(self.sec_user_agent)})"
        )

    def available(self, provider: str) -> bool:
        key = _provider_key(provider)
        if key in PROVIDERS_WITHOUT_CREDENTIALS:
            return True
        if key == "tiingo":
            return bool(self.tiingo_api_key)
        if key == "fmp":
            return bool(self.fmp_api_key)
        if key == "sec":
            return bool(self.sec_user_agent)
        raise ValueError(f"unsupported provider: {provider}")

    def missing_reason(self, provider: str) -> str | None:
        key = _provider_key(provider)
        if self.available(key):
            return None
        env_key = PROVIDER_ENV_KEYS[key]
        return f"{env_key} is not set"

    def redact(self, text: str) -> str:
        result = str(text)
        for value in (self.tiingo_api_key, self.fmp_api_key, self.sec_user_agent):
            if value:
                result = result.replace(value, "<redacted>")
        return result


def load_provider_config(env: Mapping[str, str] | None = None) -> ProviderConfig:
    source = environ if env is None else env
    return ProviderConfig(
        tiingo_api_key=_optional_env(source, "TIINGO_API_KEY"),
        fmp_api_key=_optional_env(source, "FMP_API_KEY"),
        sec_user_agent=_optional_env(source, "SEC_USER_AGENT"),
    )


def _optional_env(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _provider_key(provider: str) -> str:
    key = str(provider).strip().lower().replace("-", "_")
    if key == "nasdaq_trader":
        return "nasdaq"
    return key


def _presence(value: str | None) -> str:
    return "<set>" if value else "<missing>"
