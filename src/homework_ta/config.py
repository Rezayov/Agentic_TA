"""Runtime settings with safe JSONC provider and environment configuration."""

import json
from dataclasses import dataclass
from ipaddress import ip_address
from json import JSONDecodeError
from os import environ
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_LOCAL_API_KEY = "local-dev-b5cf4ea7d481"
DEFAULT_LLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_LLM_MODEL = "local-model"
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
DEFAULT_LLM_MAX_RETRIES = 2
DEFAULT_LLM_MAX_RESPONSE_BYTES = 1_000_000
DEFAULT_MINIMUM_CONFIDENCE = 0.70
DEFAULT_API_KEY_ENV = "HOMEWORK_TA_LLM_API_KEY"
PROVIDER_CONFIG_ENV = "HOMEWORK_TA_PROVIDER_CONFIG"
MAX_PROVIDER_CONFIG_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Non-secret settings loaded from a small JSONC file."""

    base_url: str
    model: str
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: float | None = None
    max_retries: int | None = None
    send_temperature: bool = True
    stream: bool = False
    response_format: str = "json_schema"
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    max_response_bytes: int = DEFAULT_LLM_MAX_RESPONSE_BYTES


@dataclass(frozen=True, slots=True)
class Settings:
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str = DEFAULT_LOCAL_API_KEY
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    llm_max_response_bytes: int = DEFAULT_LLM_MAX_RESPONSE_BYTES
    minimum_confidence: float = DEFAULT_MINIMUM_CONFIDENCE
    llm_send_temperature: bool = True
    llm_stream: bool = False
    llm_response_format: str = "json_schema"
    llm_max_tokens: int | None = None
    llm_reasoning_effort: str | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        base_url: str | None = None,
        model: str | None = None,
    ) -> "Settings":
        provider = _load_provider_config()
        provider_base_url = provider.base_url if provider else DEFAULT_LLM_BASE_URL
        provider_model = provider.model if provider else DEFAULT_LLM_MODEL
        provider_timeout = (
            provider.timeout_seconds
            if provider and provider.timeout_seconds is not None
            else DEFAULT_LLM_TIMEOUT_SECONDS
        )
        provider_retries = (
            provider.max_retries
            if provider and provider.max_retries is not None
            else DEFAULT_LLM_MAX_RETRIES
        )
        api_key_env = provider.api_key_env if provider else DEFAULT_API_KEY_ENV
        api_key = environ.get(api_key_env)
        if provider and api_key is None:
            raise ValueError(f"{api_key_env} must be set when {PROVIDER_CONFIG_ENV} is configured")

        settings = cls(
            llm_base_url=base_url or environ.get("HOMEWORK_TA_LLM_BASE_URL", provider_base_url),
            llm_api_key=api_key if api_key is not None else DEFAULT_LOCAL_API_KEY,
            llm_model=model or environ.get("HOMEWORK_TA_LLM_MODEL", provider_model),
            llm_send_temperature=provider.send_temperature if provider else True,
            llm_stream=provider.stream if provider else False,
            llm_response_format=provider.response_format if provider else "json_schema",
            llm_max_tokens=provider.max_tokens if provider else None,
            llm_reasoning_effort=provider.reasoning_effort if provider else None,
            llm_timeout_seconds=_environment_float(
                "HOMEWORK_TA_LLM_TIMEOUT_SECONDS", provider_timeout
            ),
            llm_max_retries=_environment_int("HOMEWORK_TA_LLM_MAX_RETRIES", provider_retries),
            llm_max_response_bytes=_environment_int(
                "HOMEWORK_TA_LLM_MAX_RESPONSE_BYTES",
                provider.max_response_bytes if provider else DEFAULT_LLM_MAX_RESPONSE_BYTES,
            ),
            minimum_confidence=_environment_float(
                "HOMEWORK_TA_MINIMUM_CONFIDENCE", DEFAULT_MINIMUM_CONFIDENCE
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        validate_provider_url(self.llm_base_url)
        if not self.llm_api_key.strip():
            raise ValueError("HOMEWORK_TA_LLM_API_KEY cannot be empty")
        if not self.llm_model.strip():
            raise ValueError("HOMEWORK_TA_LLM_MODEL cannot be empty")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("LLM timeout must be positive")
        if not 0 <= self.llm_max_retries <= 10:
            raise ValueError("LLM max retries must be between 0 and 10")
        if not 1_024 <= self.llm_max_response_bytes <= 10_000_000:
            raise ValueError("LLM max response bytes must be between 1024 and 10000000")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum confidence must be between 0 and 1")


def validate_provider_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("LLM base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("LLM base URL must not contain a query or fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError("plain HTTP is allowed only for a loopback LLM provider")


def _load_provider_config() -> ProviderConfig | None:
    configured_path = environ.get(PROVIDER_CONFIG_ENV)
    if configured_path is None:
        return None
    if not configured_path.strip():
        raise ValueError(f"{PROVIDER_CONFIG_ENV} cannot be empty")

    path = Path(configured_path).expanduser()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"cannot read provider config {path}: {exc}") from exc
    if size > MAX_PROVIDER_CONFIG_BYTES:
        raise ValueError(f"provider config exceeds the {MAX_PROVIDER_CONFIG_BYTES}-byte limit")

    try:
        document = json.loads(_strip_jsonc_comments(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, JSONDecodeError) as exc:
        raise ValueError(f"invalid provider config {path}: {exc}") from exc
    return _parse_provider_config(document, path)


def _parse_provider_config(document: Any, path: Path) -> ProviderConfig:
    if not isinstance(document, dict):
        raise ValueError(f"provider config {path} must contain a JSON object")

    allowed = {
        "base_url",
        "model",
        "api_key_env",
        "timeout_seconds",
        "max_retries",
        "send_temperature",
        "stream",
        "response_format",
        "max_tokens",
        "reasoning_effort",
        "max_response_bytes",
    }
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise ValueError(f"provider config {path} has unknown fields: {', '.join(unknown)}")

    base_url = _required_config_string(document, "base_url", path)
    model = _required_config_string(document, "model", path)
    api_key_env = document.get("api_key_env", DEFAULT_API_KEY_ENV)
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise ValueError(f"provider config {path} field api_key_env must be a string")

    timeout_seconds = document.get("timeout_seconds")
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
    ):
        raise ValueError(f"provider config {path} field timeout_seconds must be a number")

    max_retries = document.get("max_retries")
    if max_retries is not None and (
        isinstance(max_retries, bool) or not isinstance(max_retries, int)
    ):
        raise ValueError(f"provider config {path} field max_retries must be an integer")

    send_temperature = document.get("send_temperature", True)
    if not isinstance(send_temperature, bool):
        raise ValueError(f"provider config {path} field send_temperature must be a boolean")
    stream = document.get("stream", False)
    if not isinstance(stream, bool):
        raise ValueError(f"provider config {path} field stream must be a boolean")
    response_format = document.get("response_format", "json_schema")
    if response_format not in ("json_schema", "json_object", "prompt"):
        raise ValueError("provider response_format must be json_schema, json_object, or prompt")
    max_tokens = document.get("max_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= 65_536
    ):
        raise ValueError("provider max_tokens must be an integer between 1 and 65536")
    reasoning_effort = document.get("reasoning_effort")
    if reasoning_effort not in (None, "low", "high", "max"):
        raise ValueError("provider reasoning_effort must be low, high, or max")
    max_response_bytes = document.get("max_response_bytes", DEFAULT_LLM_MAX_RESPONSE_BYTES)
    if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
        raise ValueError("provider max_response_bytes must be an integer")

    return ProviderConfig(
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
        timeout_seconds=float(timeout_seconds) if timeout_seconds is not None else None,
        max_retries=max_retries,
        send_temperature=send_temperature,
        stream=stream,
        response_format=response_format,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        max_response_bytes=max_response_bytes,
    )


def _required_config_string(document: dict[str, Any], name: str, path: Path) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"provider config {path} field {name} must be a non-empty string")
    return value


def _strip_jsonc_comments(source: str) -> str:
    """Remove JSONC comments without touching comment markers inside strings."""

    result: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if in_string:
            result.append(current)
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
            index += 1
            continue

        if current == '"':
            in_string = True
            result.append(current)
            index += 1
        elif current == "/" and following == "/":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
        elif current == "/" and following == "*":
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                if source[index] in "\r\n":
                    result.append(source[index])
                index += 1
            if index + 1 >= len(source):
                raise ValueError("provider config contains an unterminated block comment")
            index += 2
        else:
            result.append(current)
            index += 1

    return "".join(result)


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _environment_int(name: str, default: int) -> int:
    value = environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _environment_float(name: str, default: float) -> float:
    value = environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
