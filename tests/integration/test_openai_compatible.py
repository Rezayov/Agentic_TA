import json
from email.message import Message
from http.client import RemoteDisconnected
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest
from pytest import MonkeyPatch

from homework_ta.application.ports.llm import ChatMessage, LLMRequest
from homework_ta.infrastructure.llm import openai_compatible
from homework_ta.infrastructure.llm.openai_compatible import OpenAICompatibleLLM, ProviderError


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return json.dumps(
            {
                "model": "test-model",
                "choices": [{"message": {"content": '{"ok": true}'}}],
            }
        ).encode()


@pytest.mark.parametrize(
    "header,delay,attempt_count", [("10", 10, 2), ("bad", 1, 2), ("120", None, 1)]
)
def test_provider_respects_bounded_server_cooldown(
    monkeypatch: MonkeyPatch, header: str, delay: int | None, attempt_count: int
) -> None:
    attempts = 0
    delays: list[float] = []
    headers = Message()
    headers["Retry-After"] = header

    def limited_urlopen(request: Any, timeout: float) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(request.full_url, 429, "at capacity", headers, BytesIO(b"{}"))
        return FakeResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", limited_urlopen)
    monkeypatch.setattr(openai_compatible.time, "sleep", delays.append)
    client = OpenAICompatibleLLM(
        base_url="http://127.0.0.1:8000/v1", api_key="test-key", model="test-model", max_retries=1
    )
    request = LLMRequest(
        messages=(ChatMessage(role="user", content="hello"),),
        response_schema={"type": "object"},
        schema_name="Result",
    )
    if delay is None:
        with pytest.raises(ProviderError, match="HTTP status 429"):
            client.complete(request)
    else:
        assert client.complete(request).content == '{"ok": true}'
    assert attempts == attempt_count
    assert delays == ([] if delay is None else [delay])


def test_openai_compatible_request_and_response_contract(monkeypatch: MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        received["url"] = request.full_url
        received["authorization"] = request.headers["Authorization"]
        received["body"] = json.loads(request.data)
        received["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = OpenAICompatibleLLM(
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        model="test-model",
        max_retries=0,
    )
    result = client.complete(
        LLMRequest(
            messages=(ChatMessage(role="user", content="hello"),),
            response_schema={"type": "object"},
            schema_name="Result",
        )
    )

    assert result.content == '{"ok": true}'
    assert received["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert received["authorization"] == "Bearer test-key"
    assert received["body"]["response_format"]["type"] == "json_schema"
    assert received["body"]["stream"] is False


def test_openai_compatible_retries_remote_disconnect(monkeypatch: MonkeyPatch) -> None:
    attempts = 0

    def flaky_urlopen(request: Any, timeout: float) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemoteDisconnected("remote closed the connection")
        return FakeResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", flaky_urlopen)
    monkeypatch.setattr(openai_compatible.time, "sleep", lambda _: None)
    client = OpenAICompatibleLLM(
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        model="test-model",
        max_retries=1,
    )

    result = client.complete(
        LLMRequest(
            messages=(ChatMessage(role="user", content="hello"),),
            response_schema={"type": "object"},
            schema_name="Result",
        )
    )

    assert result.content == '{"ok": true}'
    assert attempts == 2


def test_provider_can_omit_unsupported_generation_parameters(monkeypatch: MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        received.update(json.loads(request.data))
        return FakeResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = OpenAICompatibleLLM(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
        send_temperature=False,
        response_format="prompt",
    )
    client.complete(
        LLMRequest(
            messages=(ChatMessage(role="user", content="schema is in this prompt"),),
            response_schema={"type": "object"},
            schema_name="Result",
        )
    )

    assert "temperature" not in received
    assert "response_format" not in received
    assert received["messages"][0]["content"] == "schema is in this prompt"


def stream_bytes(*, finish_reason: str = "stop", done: bool = True) -> bytes:
    chunks = [
        {"model": "test-model", "choices": [{"index": 0, "delta": {"content": '{"ok":'}}]},
        {"choices": [{"index": 0, "delta": {"content": " true}"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]},
    ]
    lines = [": keep-alive", *("data: " + json.dumps(chunk) for chunk in chunks)]
    if done:
        lines.append("data: [DONE]")
    return "\n\n".join(lines).encode()


def test_stream_collects_content_and_ignores_keepalive() -> None:
    result = OpenAICompatibleLLM._parse_stream(stream_bytes())

    assert result.content == '{"ok": true}'
    assert result.model == "test-model"


@pytest.mark.parametrize(
    "raw",
    [stream_bytes(done=False), stream_bytes(finish_reason="length"), b"data: [DONE]\n"],
)
def test_stream_rejects_incomplete_truncated_and_empty_completions(raw: bytes) -> None:
    with pytest.raises(ProviderError):
        OpenAICompatibleLLM._parse_stream(raw)


def test_non_streaming_rejects_truncated_completion() -> None:
    raw = json.dumps(
        {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "length"}]}
    ).encode()

    with pytest.raises(ProviderError, match="finish normally"):
        OpenAICompatibleLLM._parse_response(raw)


def test_streamed_provider_request_uses_configured_budget(monkeypatch: MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    class StreamResponse(FakeResponse):
        def __init__(self) -> None:
            self.body = BytesIO(stream_bytes())

        def readline(self, limit: int) -> bytes:
            return self.body.readline(limit)

    def fake_urlopen(request: Any, timeout: float) -> StreamResponse:
        received.update(json.loads(request.data))
        return StreamResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = OpenAICompatibleLLM(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
        stream=True,
        max_tokens=16384,
        reasoning_effort="low",
    )
    result = client.complete(
        LLMRequest(
            messages=(ChatMessage(role="user", content="hello"),),
            response_schema={"type": "object"},
            schema_name="Result",
        )
    )

    assert result.content == '{"ok": true}'
    assert received["stream"] is True
    assert received["max_tokens"] == 16384
    assert received["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_stream_reader_enforces_transport_size_limit() -> None:
    client = OpenAICompatibleLLM(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
        stream=True,
        max_response_bytes=1024,
    )

    with pytest.raises(ProviderError, match="size limit"):
        client._read_stream(BytesIO(b"data: " + b"x" * 2048), "Result", 0)


def test_incomplete_stream_is_retried_as_a_transport_failure(monkeypatch: MonkeyPatch) -> None:
    attempts = 0

    class StreamResponse(FakeResponse):
        def __init__(self, raw: bytes) -> None:
            self.body = BytesIO(raw)

        def readline(self, limit: int) -> bytes:
            return self.body.readline(limit)

    def flaky_urlopen(request: Any, timeout: float) -> StreamResponse:
        nonlocal attempts
        attempts += 1
        return StreamResponse(stream_bytes(done=attempts > 1))

    monkeypatch.setattr(openai_compatible, "urlopen", flaky_urlopen)
    monkeypatch.setattr(openai_compatible.time, "sleep", lambda _: None)
    client = OpenAICompatibleLLM(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
        stream=True,
        max_retries=1,
    )
    result = client.complete(
        LLMRequest(
            messages=(ChatMessage(role="user", content="hello"),),
            response_schema={"type": "object"},
            schema_name="Result",
        )
    )

    assert result.content == '{"ok": true}'
    assert attempts == 2


def test_stream_stats_count_reasoning_without_retaining_its_text() -> None:
    stats = openai_compatible._StreamStats()
    stats.observe(
        b'data: {"choices":[{"delta":{"reasoning":"PRIVATE_THOUGHT", "content":"ok"}}]}\n'
    )
    stats.observe(b'data: {"usage":{"completion_tokens":25}, "choices":[]}\n')
    stats.observe(b"data: [DONE]\n")

    assert stats.content_characters == 2
    assert stats.reasoning_characters == len("PRIVATE_THOUGHT")
    assert stats.completion_tokens == 25
    assert stats.done is True
    assert "PRIVATE_THOUGHT" not in repr(stats)
