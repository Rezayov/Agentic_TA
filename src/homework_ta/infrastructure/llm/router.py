"""Ordered failover using the LiteLLM SDK, without a separate gateway service."""

import json
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from homework_ta.application.ports.llm import LLMRequest, LLMResponse
from homework_ta.config import (
    MAX_PROVIDER_CONFIG_BYTES,
    ProviderConfig,
    Settings,
    _parse_provider_config,
    _strip_jsonc_comments,
)
from homework_ta.infrastructure.llm.openai_compatible import ProviderError
from homework_ta.observability import log_event

LOGGER = logging.getLogger("homework_ta.router")


@dataclass(frozen=True)
class Route:
    name: str
    provider: ProviderConfig
    models: tuple[str, ...] = ()

    @property
    def ordered_models(self) -> tuple[str, ...]:
        return self.models or (self.provider.model,)


@dataclass(frozen=True)
class RouterConfig:
    providers: tuple[Route, ...]
    failure_threshold: int = 3
    retry_delay_seconds: float = 1.0

    @classmethod
    def load(cls, path: Path) -> "RouterConfig":
        with path.open("rb") as handle:
            raw = handle.read(MAX_PROVIDER_CONFIG_BYTES + 1)
        if len(raw) > MAX_PROVIDER_CONFIG_BYTES:
            raise ValueError("router configuration is too large")
        document = json.loads(_strip_jsonc_comments(raw.decode("utf-8")))
        if not isinstance(document, dict) or set(document) - {
            "providers",
            "failure_threshold",
            "retry_delay_seconds",
        }:
            raise ValueError("invalid router configuration fields")
        threshold = document.get("failure_threshold", 3)
        delay = document.get("retry_delay_seconds", 1.0)
        if type(threshold) is not int or threshold not in (2, 3):
            raise ValueError("failure_threshold must be 2 or 3 total attempts per model")
        if type(delay) not in (int, float) or not 0 <= delay <= 30:
            raise ValueError("retry_delay_seconds must be between 0 and 30")
        entries = document.get("providers")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 10:
            raise ValueError("providers must contain 1 to 10 ordered entries")
        routes = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("each provider must be an object")
            name = entry.get("name")
            if not isinstance(name, str) or not name.isidentifier() or len(name) > 50:
                raise ValueError("provider name must be a short identifier")
            if "models" in entry and "model" in entry:
                raise ValueError("use either model or models, not both")
            models = entry.get("models", [entry.get("model")])
            if (
                not isinstance(models, list)
                or not 1 <= len(models) <= 10
                or any(not isinstance(model, str) or not model.strip() for model in models)
            ):
                raise ValueError("models must contain 1 to 10 non-empty model IDs")
            models = [model.strip() for model in models]
            if len(set(models)) != len(models):
                raise ValueError("models must not contain duplicate IDs")
            provider = _parse_provider_config(
                {
                    **{key: value for key, value in entry.items() if key not in {"name", "models"}},
                    "model": models[0],
                },
                path,
            )
            if not provider.api_key_env.isidentifier():
                raise ValueError("api_key_env must name an environment variable, not contain a key")
            Settings(
                llm_base_url=provider.base_url,
                llm_model=provider.model,
                llm_timeout_seconds=(
                    provider.timeout_seconds if provider.timeout_seconds is not None else 60
                ),
                llm_max_retries=provider.max_retries or 0,
                llm_max_response_bytes=provider.max_response_bytes,
            ).validate()
            if provider.max_retries is not None:
                raise ValueError(
                    "router owns retries; use failure_threshold instead of max_retries"
                )
            routes.append(Route(name, provider, tuple(models)))
        if len({route.name for route in routes}) != len(routes):
            raise ValueError("provider names must be unique")
        return cls(tuple(routes), threshold, float(delay))


class LiteLLMRouter:
    """Stick to a healthy route for the run; retire it after bounded failed attempts.

    SDK retries are disabled to make the configured threshold exact. Both assessors
    share transport only: no response, conversation, or grading state is cached here.
    """

    def __init__(self, config: RouterConfig) -> None:
        self.config = config
        self._index = 0
        self._model_index = 0
        self._keys = {}
        for route in config.providers:
            key = os.environ.get(route.provider.api_key_env, "").strip()
            if key:
                self._keys[route.name] = key
        if not self._keys:
            raise ValueError("set at least one configured provider API key environment variable")

    def complete(self, request: LLMRequest) -> LLMResponse:
        import litellm

        # Prevent SDK error diagnostics from dumping prompts or credentials.
        litellm.suppress_debug_info = True
        while self._index < len(self.config.providers):
            configured_route = self.config.providers[self._index]
            route = replace(
                configured_route,
                provider=replace(
                    configured_route.provider,
                    model=configured_route.ordered_models[self._model_index],
                ),
            )
            if route.name not in self._keys:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "provider_skipped",
                    provider=route.name,
                    reason="missing_key",
                )
                self._index += 1
                self._model_index = 0
                continue
            for attempt in range(1, self.config.failure_threshold + 1):
                try:
                    response = litellm.completion(**self._parameters(route, request))
                    result = self._read_response(response, route, request)
                    log_event(
                        LOGGER,
                        logging.INFO,
                        "router_completion",
                        provider=route.name,
                        model=result.model,
                        schema_name=request.schema_name,
                        attempt=attempt,
                    )
                    return result
                except Exception as exc:
                    # Never print provider exception text: it may contain credentials/content.
                    log_event(
                        LOGGER,
                        logging.WARNING,
                        "router_attempt_failed",
                        provider=route.name,
                        model=route.provider.model,
                        schema_name=request.schema_name,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                    )
                    if attempt < self.config.failure_threshold:
                        time.sleep(self.config.retry_delay_seconds)
            log_event(
                LOGGER,
                logging.WARNING,
                "model_failover",
                provider=route.name,
                model=route.provider.model,
            )
            self._model_index += 1
            if self._model_index == len(configured_route.ordered_models):
                log_event(LOGGER, logging.WARNING, "provider_failover", provider=route.name)
                self._index += 1
                self._model_index = 0
        raise ProviderError(
            "all configured providers failed or were unavailable; inspect router logs"
        )

    def _parameters(self, route: Route, request: LLMRequest) -> dict[str, Any]:
        provider = route.provider
        parameters: dict[str, Any] = {
            "model": f"openai/{provider.model}",
            "api_base": provider.base_url,
            "api_key": self._keys[route.name],
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "timeout": provider.timeout_seconds if provider.timeout_seconds is not None else 60,
            "num_retries": 0,
            "stream": provider.stream,
        }
        if provider.response_format == "json_schema":
            parameters["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        elif provider.response_format == "json_object":
            parameters["response_format"] = {"type": "json_object"}
        if provider.send_temperature:
            parameters["temperature"] = request.temperature
        if provider.max_tokens is not None:
            parameters["max_tokens"] = provider.max_tokens
        if provider.reasoning_effort:
            parameters["extra_body"] = {
                "chat_template_kwargs": {"reasoning_effort": provider.reasoning_effort}
            }
        return parameters

    @staticmethod
    def _read_response(response: Any, route: Route, request: LLMRequest) -> LLMResponse:
        pieces = []
        finish = None
        model = None
        size = 0
        try:
            for part in response if route.provider.stream else (response,):
                choice = part.choices[0] if part.choices else None
                if choice is None:
                    continue
                model = part.model or model
                finish = choice.finish_reason or finish
                message = choice.delta if route.provider.stream else choice.message
                content = message.content or ""
                size += len(part.model_dump_json().encode("utf-8"))
                if size > route.provider.max_response_bytes:
                    raise ProviderError("completion exceeds configured response limit")
                pieces.append(content)
        finally:
            if route.provider.stream and hasattr(response, "close"):
                response.close()
        content = "".join(pieces)
        if finish != "stop" or not content.strip():
            raise ProviderError("completion is empty, truncated, or incomplete")
        try:
            validate(json.loads(content), request.response_schema)
        except (ValueError, ValidationError) as exc:
            raise ProviderError("completion does not satisfy the requested JSON schema") from exc
        return LLMResponse(content=content, model=model)
