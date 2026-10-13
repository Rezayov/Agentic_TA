"""Minimal, bounded OpenAI-compatible chat-completions adapter."""

import json
import logging
import time
from dataclasses import dataclass
from hashlib import sha256
from json import JSONDecodeError
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from homework_ta.application.ports.llm import LLMRequest, LLMResponse
from homework_ta.config import validate_provider_url
from homework_ta.observability import log_event

LOGGER = logging.getLogger("homework_ta.provider")


class ProviderError(RuntimeError):
    """Raised when the provider cannot produce a valid completion."""


class IncompleteStreamError(ProviderError):
    """A transient transport stream ended before a usable completion."""


@dataclass(slots=True)
class _StreamStats:
    content_characters: int = 0
    reasoning_characters: int = 0
    completion_tokens: int | None = None
    finish_reason: str | None = None
    done: bool = False

    def observe(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if data == b"[DONE]":
            self.done = True
            return
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError):
            return  # The authoritative parser will reject malformed data later.
        if not isinstance(payload, dict):
            return
        usage = payload.get("usage")
        if isinstance(usage, dict) and type(usage.get("completion_tokens")) is int:
            self.completion_tokens = usage["completion_tokens"]
        choices = payload.get("choices", [])
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            reason = choice.get("finish_reason")
            if isinstance(reason, str):
                self.finish_reason = (
                    reason
                    if reason in {"stop", "length", "content_filter", "tool_calls", "function_call"}
                    else "unexpected"
                )
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            reasoning = delta.get("reasoning", delta.get("reasoning_content"))
            if isinstance(content, str):
                self.content_characters += len(content)
            if isinstance(reasoning, str):
                self.reasoning_characters += len(reasoning)


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60,
        max_retries: int = 2,
        max_response_bytes: int = 1_000_000,
        send_temperature: bool = True,
        stream: bool = False,
        response_format: str = "json_schema",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        validate_provider_url(base_url)
        if not api_key.strip():
            raise ValueError("provider API key cannot be empty")
        if not model.strip():
            raise ValueError("provider model cannot be empty")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        if not 0 <= max_retries <= 10:
            raise ValueError("provider max retries must be between 0 and 10")
        if not 1_024 <= max_response_bytes <= 10_000_000:
            raise ValueError("provider response limit must be between 1024 and 10000000")
        if response_format not in {"json_schema", "json_object", "prompt"}:
            raise ValueError("unsupported provider response format")
        if max_tokens is not None and not 1 <= max_tokens <= 65_536:
            raise ValueError("provider max tokens must be between 1 and 65536")
        if reasoning_effort not in {None, "low", "high", "max"}:
            raise ValueError("unsupported provider reasoning effort")
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._send_temperature = send_temperature
        self._stream = stream
        self._response_format = response_format
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort

    def complete(self, request: LLMRequest) -> LLMResponse:
        schema_bytes = json.dumps(
            request.response_schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload = {
            "model": self._model,
            "stream": self._stream,
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
        }
        if self._response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif self._response_format == "prompt":
            del payload["response_format"]
        if self._send_temperature:
            payload["temperature"] = request.temperature
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._reasoning_effort is not None:
            payload["chat_template_kwargs"] = {"reasoning_effort": self._reasoning_effort}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(self._max_retries + 1):
            retry_delay = min(2**attempt, 4)
            started_at = time.monotonic()
            log_event(
                LOGGER,
                logging.INFO,
                "provider_request_started",
                attempt=attempt + 1,
                schema_name=request.schema_name,
                requested_model=self._model,
                message_count=len(request.messages),
                request_bytes=len(body),
                schema_bytes=len(schema_bytes),
                schema_sha256=sha256(schema_bytes).hexdigest(),
                send_temperature=self._send_temperature,
                stream=self._stream,
                response_format=self._response_format,
                max_tokens=self._max_tokens,
                reasoning_effort=self._reasoning_effort,
            )
            http_request = Request(
                self._endpoint,
                data=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream" if self._stream else "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(http_request, timeout=self._timeout_seconds) as response:
                    request_id = _request_id(response)
                    if self._stream:
                        raw = self._read_stream(response, request.schema_name, started_at)
                    else:
                        raw = response.read(self._max_response_bytes + 1)
                if len(raw) > self._max_response_bytes:
                    raise ProviderError("provider response exceeded configured size limit")
                parsed = self._parse_stream(raw) if self._stream else self._parse_response(raw)
                log_event(
                    LOGGER,
                    logging.INFO,
                    "provider_response_received",
                    attempt=attempt + 1,
                    schema_name=request.schema_name,
                    requested_model=self._model,
                    provider_model=parsed.model,
                    response_bytes=len(raw),
                    content_characters=len(parsed.content),
                    content_sha256=sha256(parsed.content.encode("utf-8")).hexdigest(),
                    request_id=request_id,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                )
                return parsed
            except HTTPError as exc:
                retryable = exc.code in {408, 409, 425, 429} or exc.code >= 500
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                if retry_after.isascii() and retry_after.isdecimal():
                    # Bound parsing and waiting; never retry before a long server cooldown.
                    if len(retry_after) > 2 or int(retry_after) > 60:
                        retryable = False
                    else:
                        retry_delay = max(retry_delay, int(retry_after))
                exc.read(4_096)
                error = ProviderError(f"provider returned HTTP status {exc.code}")
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "provider_http_error",
                    attempt=attempt + 1,
                    schema_name=request.schema_name,
                    requested_model=self._model,
                    status=exc.code,
                    retryable=retryable,
                    retry_delay_seconds=retry_delay if retryable else None,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                )
                if not retryable or attempt == self._max_retries:
                    raise error from exc
            except (TimeoutError, URLError, ConnectionError) as exc:
                detail = exc.reason if isinstance(exc, URLError) else exc
                error = ProviderError(f"provider connection failed: {detail}")
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "provider_connection_error",
                    attempt=attempt + 1,
                    schema_name=request.schema_name,
                    requested_model=self._model,
                    error_type=type(detail).__name__,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                )
                if attempt == self._max_retries:
                    raise error from exc
            except IncompleteStreamError:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "provider_incomplete_stream",
                    attempt=attempt + 1,
                    schema_name=request.schema_name,
                    retryable=True,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                )
                if attempt == self._max_retries:
                    raise

            time.sleep(retry_delay)

        raise AssertionError("provider retry loop exited unexpectedly")

    def _read_stream(self, response: BinaryIO, schema_name: str, started_at: float) -> bytes:
        chunks: list[bytes] = []
        stats = _StreamStats()
        total = 0
        last_progress = started_at
        while True:
            line = response.readline(self._max_response_bytes - total + 1)
            if not line:
                break
            total += len(line)
            if total > self._max_response_bytes:
                raise ProviderError("provider response exceeded configured size limit")
            chunks.append(line)
            stats.observe(line)
            now = time.monotonic()
            if now - last_progress >= 15:
                log_event(
                    LOGGER,
                    logging.INFO,
                    "provider_stream_progress",
                    schema_name=schema_name,
                    response_bytes=total,
                    duration_ms=round((now - started_at) * 1000),
                    content_characters=stats.content_characters,
                    reasoning_characters=stats.reasoning_characters,
                )
                last_progress = now
            if line.strip() == b"data: [DONE]":
                break
        log_event(
            LOGGER,
            logging.INFO,
            "provider_stream_finished",
            schema_name=schema_name,
            response_bytes=total,
            content_characters=stats.content_characters,
            reasoning_characters=stats.reasoning_characters,
            completion_tokens=stats.completion_tokens,
            finish_reason=stats.finish_reason,
            done=stats.done,
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
        return b"".join(chunks)

    @staticmethod
    def _parse_response(raw: bytes) -> LLMResponse:
        try:
            payload = json.loads(raw.decode("utf-8"))
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (UnicodeDecodeError, JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider returned an invalid chat-completions response") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("provider returned empty or non-text completion content")
        _validate_finish_reason(choice.get("finish_reason"))
        model = payload.get("model")
        return LLMResponse(
            content=content,
            model=model if isinstance(model, str) else None,
        )

    @staticmethod
    def _parse_stream(raw: bytes) -> LLMResponse:
        """Collect bounded OpenAI SSE content; reject incomplete or failed streams."""

        fragments: list[str] = []
        model: str | None = None
        finished = False
        done = False
        try:
            for line in raw.decode("utf-8").splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                payload = json.loads(data)
                if "error" in payload:
                    raise ProviderError("provider stream reported an error")
                if isinstance(payload.get("model"), str):
                    model = payload["model"]
                for choice in payload.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        _validate_finish_reason(reason)
                        finished = True
                    content = choice.get("delta", {}).get("content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise ProviderError("provider returned non-text streamed content")
                        fragments.append(content)
        except (UnicodeDecodeError, JSONDecodeError, TypeError, AttributeError) as exc:
            raise ProviderError("provider returned an invalid chat-completions stream") from exc
        content = "".join(fragments)
        if not done or not finished or not content.strip():
            raise IncompleteStreamError(
                "provider returned an incomplete or empty completion stream "
                f"(done={done}, stopped={finished}, content_characters={len(content)})"
            )
        return LLMResponse(content=content, model=model)


def _request_id(response: object) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("x-request-id", "request-id", "x-correlation-id"):
        value = headers.get(name)
        if value:
            return str(value)[:200]
    return None


def _validate_finish_reason(reason: object) -> None:
    if reason is None or reason == "stop":
        return
    known_reasons = ("length", "content_filter", "tool_calls", "function_call")
    detail = reason if reason in known_reasons else "unexpected reason"
    raise ProviderError(f"provider completion did not finish normally ({detail})")
