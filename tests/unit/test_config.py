import pytest

from homework_ta.config import Settings


def test_default_settings_use_loopback_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOMEWORK_TA_PROVIDER_CONFIG", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_MODEL", raising=False)
    settings = Settings.from_environment()

    assert settings.llm_base_url == "http://localhost:8000/v1"
    assert settings.llm_api_key.startswith("local-dev-")


def test_plain_http_is_rejected_for_remote_provider() -> None:
    with pytest.raises(ValueError, match="loopback"):
        Settings(llm_base_url="http://example.com/v1").validate()


def test_https_is_allowed_for_remote_provider() -> None:
    Settings(llm_base_url="https://example.com/v1").validate()


def test_jsonc_provider_config_loads_https_url_and_comments(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "provider.jsonc"
    config_path.write_text(
        """
        {
          // The slashes in this URL are part of its JSON string.
          "base_url": "https://inference.example/v1",
          "api_key_env": "TEST_PROVIDER_KEY",
          "model": "example/model",
          /* Values here are defaults that environment variables may override. */
          "timeout_seconds": 45,
          "max_retries": 3,
          "send_temperature": false,
          "stream": true,
          "response_format": "prompt",
          "max_tokens": 16384,
          "reasoning_effort": "low",
          "max_response_bytes": 10000000
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("HOMEWORK_TA_PROVIDER_CONFIG", str(config_path))
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-secret")
    monkeypatch.delenv("HOMEWORK_TA_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_MODEL", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_LLM_MAX_RETRIES", raising=False)

    settings = Settings.from_environment()

    assert settings.llm_base_url == "https://inference.example/v1"
    assert settings.llm_api_key == "test-secret"
    assert settings.llm_model == "example/model"
    assert settings.llm_timeout_seconds == 45
    assert settings.llm_max_retries == 3
    assert settings.llm_send_temperature is False
    assert settings.llm_stream is True
    assert settings.llm_response_format == "prompt"
    assert settings.llm_max_tokens == 16384
    assert settings.llm_reasoning_effort == "low"
    assert settings.llm_max_response_bytes == 10000000


def test_environment_overrides_jsonc_provider_values(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "provider.jsonc"
    config_path.write_text(
        '{"base_url":"https://file.example/v1","model":"file-model"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOMEWORK_TA_PROVIDER_CONFIG", str(config_path))
    monkeypatch.setenv("HOMEWORK_TA_LLM_API_KEY", "test-secret")
    monkeypatch.setenv("HOMEWORK_TA_LLM_BASE_URL", "https://environment.example/v1")
    monkeypatch.setenv("HOMEWORK_TA_LLM_MODEL", "environment-model")

    settings = Settings.from_environment()

    assert settings.llm_base_url == "https://environment.example/v1"
    assert settings.llm_model == "environment-model"


def test_jsonc_provider_requires_named_api_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "provider.jsonc"
    config_path.write_text(
        """{
          "base_url": "https://inference.example/v1",
          "model": "example-model",
          "api_key_env": "MISSING_TEST_PROVIDER_KEY"
        }""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOMEWORK_TA_PROVIDER_CONFIG", str(config_path))
    monkeypatch.delenv("MISSING_TEST_PROVIDER_KEY", raising=False)

    with pytest.raises(ValueError, match="MISSING_TEST_PROVIDER_KEY must be set"):
        Settings.from_environment()


def test_jsonc_provider_rejects_unknown_fields(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "provider.jsonc"
    config_path.write_text(
        """{
          "base_url": "https://inference.example/v1",
          "model": "example-model",
          "unexpected": true
        }""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOMEWORK_TA_PROVIDER_CONFIG", str(config_path))

    with pytest.raises(ValueError, match="unknown fields: unexpected"):
        Settings.from_environment()
