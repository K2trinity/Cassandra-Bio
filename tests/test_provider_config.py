from __future__ import annotations


def test_load_provider_config_reads_env_without_exposing_values(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-secret")
    monkeypatch.setenv("SEC_USER_AGENT", "CassandraBio user@example.com")

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()

    assert config.tiingo_api_key == "tiingo-secret"
    assert config.fmp_api_key == "fmp-secret"
    assert config.sec_user_agent == "CassandraBio user@example.com"
    assert "tiingo-secret" not in repr(config)
    assert "fmp-secret" not in repr(config)
    assert "user@example.com" not in repr(config)


def test_provider_config_reports_missing_required_provider_credentials(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()

    assert config.available("nasdaq") is True
    assert config.available("tiingo") is False
    assert config.available("fmp") is False
    assert config.available("sec") is False
    assert config.missing_reason("tiingo") == "TIINGO_API_KEY is not set"
    assert config.missing_reason("fmp") == "FMP_API_KEY is not set"
    assert config.missing_reason("sec") == "SEC_USER_AGENT is not set"


def test_redact_text_removes_configured_secret_values(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-secret")
    monkeypatch.setenv("SEC_USER_AGENT", "CassandraBio user@example.com")

    from src.data_ingestion.provider_config import load_provider_config

    config = load_provider_config()
    redacted = config.redact(
        "token=tiingo-secret apikey=fmp-secret agent=CassandraBio user@example.com"
    )

    assert redacted == "token=<redacted> apikey=<redacted> agent=<redacted>"
