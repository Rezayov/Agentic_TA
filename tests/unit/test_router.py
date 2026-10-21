import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from homework_ta.application.ports.llm import ChatMessage, LLMRequest
from homework_ta.config import ProviderConfig
from homework_ta.infrastructure.llm.openai_compatible import ProviderError
from homework_ta.infrastructure.llm.router import LiteLLMRouter, Route, RouterConfig


def request():
    return LLMRequest(
        (ChatMessage("user", "private student answer"),),
        {
            "type": "object",
            "properties": {"answer": {"type": "integer"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        "test",
    )


def config(threshold=3):
    return RouterConfig(
        tuple(
            Route(
                name,
                ProviderConfig(
                    base_url=f"https://{name}.example/v1",
                    model="test",
                    api_key_env=name.upper(),
                    response_format="prompt",
                ),
            )
            for name in ("first", "second")
        ),
        threshold,
        0,
    )


def response(content='{"answer":14}', finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        model="test",
        model_dump_json=lambda: json.dumps({"content": content}),
    )


@pytest.mark.parametrize("threshold", [2, 3])
def test_exact_attempt_count_and_sticky_fallback(monkeypatch, threshold):
    import litellm

    monkeypatch.setenv("FIRST", "secret1")
    monkeypatch.setenv("SECOND", "secret2")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if "first" in kwargs["api_base"]:
            raise RuntimeError("secret1 private answer")
        return response()

    monkeypatch.setattr(litellm, "completion", completion)
    router = LiteLLMRouter(config(threshold))
    assert router.complete(request()).content == '{"answer":14}'
    router.complete(request())
    assert len(calls) == threshold + 2
    assert all(call["num_retries"] == 0 for call in calls)
    assert calls[0]["messages"] == calls[threshold]["messages"]


@pytest.mark.parametrize(
    "bad",
    [
        response("bad"),
        response('{"answer":"wrong"}'),
        response("", "stop"),
        response('{"answer":14}', "length"),
    ],
)
def test_invalid_completion_fails_over(monkeypatch, bad):
    import litellm

    monkeypatch.setenv("FIRST", "secret1")
    monkeypatch.setenv("SECOND", "secret2")
    monkeypatch.setattr(
        litellm, "completion", lambda **kw: bad if "first" in kw["api_base"] else response()
    )
    router = LiteLLMRouter(config())
    assert router.complete(request()).content == '{"answer":14}'
    assert router._index == 1


def test_exhaustion_is_safe_and_missing_key_skipped(monkeypatch, caplog):
    import litellm

    monkeypatch.delenv("FIRST", raising=False)
    monkeypatch.setenv("SECOND", "secret2")

    def fail(**kwargs):
        raise RuntimeError("secret2 private student answer")

    monkeypatch.setattr(litellm, "completion", fail)
    with pytest.raises(ProviderError, match="all configured providers"):
        LiteLLMRouter(config()).complete(request())
    assert "secret2" not in caplog.text
    assert "private student answer" not in caplog.text


@pytest.mark.parametrize(
    "update",
    [
        {"failure_threshold": 1},
        {"failure_threshold": True},
        {"retry_delay_seconds": float("nan")},
        {"providers": []},
        {"unknown": True},
    ],
)
def test_invalid_config(tmp_path, update):
    document = {
        "providers": [{"name": "first", "base_url": "https://first.example/v1", "model": "test"}]
    }
    document.update(update)
    path = tmp_path / "router.jsonc"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        RouterConfig.load(path)


def test_example_config():
    loaded = RouterConfig.load(Path("config/router.jsonc"))
    assert [r.name for r in loaded.providers] == ["g-cat", "gcat", "agentrouter", "dahl", "hormouz"]
    assert loaded.providers[0].ordered_models == (
        "agy/gemini-3.8-flash-high",
        "cx/gpt-6-luna-medium",
    )


def test_stream_closes_and_rejects_incomplete():
    route = Route(
        "stream", ProviderConfig(base_url="https://example.org/v1", model="test", stream=True)
    )

    class Stream:
        closed = False

        def __iter__(self):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content='{"answer":14}'), finish_reason=None
                    )
                ],
                model="test",
                model_dump_json=lambda: "{}",
            )

        def close(self):
            self.closed = True

    stream = Stream()
    with pytest.raises(ProviderError):
        LiteLLMRouter._read_response(stream, route, request())
    assert stream.closed


def test_nonpositive_timeout_rejected(tmp_path):
    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "first",
                        "base_url": "https://example.org/v1",
                        "model": "test",
                        "timeout_seconds": 0,
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="timeout"):
        RouterConfig.load(path)


def test_provider_check_uses_only_synthetic_data(monkeypatch, tmp_path):
    import litellm

    from homework_ta.interfaces import provider_cli

    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "first",
                        "base_url": "https://example.org/v1",
                        "model": "test",
                        "api_key_env": "FIRST",
                        "response_format": "prompt",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("FIRST", "secret")
    monkeypatch.setattr(provider_cli, "configure_logging", lambda path, **kwargs: None)
    seen = []

    def completion(**kwargs):
        seen.append(kwargs)
        return response()

    monkeypatch.setattr(litellm, "completion", completion)
    assert provider_cli.main(["--router-config", str(path), "--provider", "first"]) == 0
    assert "synthetic arithmetic" in seen[0]["messages"][0]["content"]
    assert len(seen[0]["messages"]) == 1


def test_hormouz_route_parameters(monkeypatch):
    monkeypatch.setenv("HORMOUZ_API_KEY", "test-hormouz-secret")
    loaded = RouterConfig.load(Path("config/router.jsonc"))
    route = next(route for route in loaded.providers if route.name == "hormouz")
    params = LiteLLMRouter(loaded)._parameters(route, request())
    assert params["model"] == "openai/qwen/qwen3.8-flash"
    assert params["api_base"] == "https://api.hormouz.net/v1"
    assert params["api_key"] == "test-hormouz-secret"
    assert params["num_retries"] == 0
    assert params["stream"] is True
    assert "response_format" not in params


@pytest.mark.parametrize("threshold", [2, 3])
def test_model_fallback_then_provider_fallback_and_sticky_selection(monkeypatch, threshold):
    from dataclasses import replace

    import litellm

    monkeypatch.setenv("FIRST", "secret1")
    monkeypatch.setenv("SECOND", "secret2")
    original = config(threshold)
    routes = (
        replace(original.providers[0], models=("bad1", "good", "bad2")),
        original.providers[1],
    )
    router = LiteLLMRouter(replace(original, providers=routes))
    calls = []
    fail_good = False

    def completion(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] in ("openai/bad1", "openai/bad2") or (
            kwargs["model"] == "openai/good" and fail_good
        ):
            raise RuntimeError("unavailable")
        return response()

    monkeypatch.setattr(litellm, "completion", completion)
    router.complete(request())
    router.complete(request())
    assert calls == ["openai/bad1"] * threshold + ["openai/good"] * 2
    fail_good = True
    router.complete(request())
    assert calls[-(threshold * 2 + 1) :] == (
        ["openai/good"] * threshold + ["openai/bad2"] * threshold + ["openai/test"]
    )
    assert router._index == 1
    assert router._model_index == 0


@pytest.mark.parametrize("models", [[], ["same", "same"], [""], "single", [None], [True]])
def test_invalid_models_rejected(tmp_path, models):
    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {"name": "test", "base_url": "https://example.org/v1", "models": models}
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="models"):
        RouterConfig.load(path)


def test_mixed_model_and_models_rejected(tmp_path):
    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "test",
                        "base_url": "https://example.org/v1",
                        "model": "one",
                        "models": ["two"],
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="either"):
        RouterConfig.load(path)


def test_plain_chat_accepts_text_and_omits_json_format(monkeypatch):
    monkeypatch.setenv("FIRST", "secret")
    router = LiteLLMRouter(config())
    chat = LLMRequest((ChatMessage("user", "hey there"),), None, "plain_chat")
    assert "response_format" not in router._parameters(config().providers[0], chat)
    assert (
        LiteLLMRouter._read_response(response("Hey there!"), config().providers[0], chat).content
        == "Hey there!"
    )


def test_plain_chat_still_rejects_truncated_response():
    chat = LLMRequest((ChatMessage("user", "hey there"),), None, "plain_chat")
    with pytest.raises(ProviderError):
        LiteLLMRouter._read_response(response("Hey", "length"), config().providers[0], chat)


def test_schema_failure_diagnostics_do_not_include_response_content():
    from homework_ta.infrastructure.llm.router import InvalidCompletionError

    with pytest.raises(InvalidCompletionError) as error:
        LiteLLMRouter._read_response(
            response('{"answer":"PRIVATE RESPONSE"}'), config().providers[0], request()
        )
    assert error.value.details["reason"] == "schema_mismatch"
    assert error.value.details["validator"] == "type"
    assert error.value.details["path"] == ["answer"]
    assert "PRIVATE RESPONSE" not in json.dumps(error.value.details)


def test_incomplete_diagnostics_distinguish_token_limit():
    from homework_ta.infrastructure.llm.router import InvalidCompletionError

    with pytest.raises(InvalidCompletionError) as error:
        LiteLLMRouter._read_response(
            response('{"answer":14}', "length"), config().providers[0], request()
        )
    assert error.value.details["finish_reason"] == "length"


@pytest.mark.parametrize("wrapper", ['```json\n{"answer":14}\n```', '```\n{"answer":14}\n```'])
def test_complete_fenced_json_is_validated(wrapper):
    result = LiteLLMRouter._read_response(response(wrapper), config().providers[0], request())
    assert result.content == '{"answer":14}'


@pytest.mark.parametrize(
    "content,finish",
    [
        ('```json\n{"answer":14}\n```', "length"),
        ('```json\n{"answer":14}', "stop"),
        ('Here it is:\n```json\n{"answer":14}\n```', "stop"),
        ('```json\n{"answer":"wrong"}\n```', "stop"),
    ],
)
def test_fence_does_not_bypass_validation(content, finish):
    with pytest.raises(ProviderError):
        LiteLLMRouter._read_response(response(content, finish), config().providers[0], request())


def test_router_emits_started_and_wait_events_before_completion(tmp_path, monkeypatch):
    from threading import Event

    import litellm

    from homework_ta.infrastructure.llm import router as module
    from homework_ta.observability import completion_progress, configure_logging

    log = tmp_path / "progress.jsonl"
    configure_logging(log)
    monkeypatch.setenv("FIRST", "secret")
    monkeypatch.delenv("SECOND", raising=False)
    monkeypatch.setattr(
        module,
        "completion_progress",
        lambda logger, **fields: completion_progress(logger, interval_seconds=0.01, **fields),
    )

    def complete(**kwargs):
        Event().wait(0.04)
        return response()

    monkeypatch.setattr(litellm, "completion", complete)
    LiteLLMRouter(config()).complete(request())
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert events[0] == "provider_request_started"
    assert "provider_request_waiting" in events[1:-1]
    assert events[-1] == "router_completion"


@pytest.mark.parametrize("name", ["g-cat", "gcat_2", "provider-one"])
def test_hyphenated_provider_names_are_supported(tmp_path, name):
    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {"name": name, "base_url": "https://example.org/v1", "models": ["test"]}
                ]
            }
        )
    )
    assert RouterConfig.load(path).providers[0].name == name


@pytest.mark.parametrize("name", ["../provider", "provider/name", "bad name", "a\nkey"])
def test_unsafe_provider_names_are_rejected(tmp_path, name):
    path = tmp_path / "router.jsonc"
    path.write_text(
        json.dumps(
            {"providers": [{"name": name, "base_url": "https://example.org/v1", "model": "test"}]}
        )
    )
    with pytest.raises(ValueError, match="provider name"):
        RouterConfig.load(path)


def test_schema_retry_receives_rule_feedback_without_rejected_content(monkeypatch):
    import litellm

    monkeypatch.setenv("FIRST", "secret")
    seen = []

    def complete(**kwargs):
        seen.append(kwargs)
        return response('{"answer":"PRIVATE BAD VALUE"}') if len(seen) == 1 else response()

    monkeypatch.setattr(litellm, "completion", complete)
    original = request()
    result = LiteLLMRouter(config()).complete(original)
    assert result.content == '{"answer":14}'
    assert seen[1]["messages"][:-1] == seen[0]["messages"]
    correction = seen[1]["messages"][-1]["content"]
    assert '"validator": "type"' in correction
    assert '"path": ["answer"]' in correction
    assert "PRIVATE BAD VALUE" not in correction
    assert len(original.messages) == 1


def test_failed_model_feedback_is_not_shared_with_next_model(monkeypatch):
    from dataclasses import replace

    import litellm

    monkeypatch.setenv("FIRST", "secret")
    configured = config(2)
    configured = replace(
        configured, providers=(replace(configured.providers[0], models=("bad", "good")),)
    )
    seen = []

    def complete(**kwargs):
        seen.append(kwargs)
        return response('{"answer":"bad"}') if kwargs["model"] == "openai/bad" else response()

    monkeypatch.setattr(litellm, "completion", complete)
    LiteLLMRouter(configured).complete(request())
    assert len(seen[1]["messages"]) == 2
    assert seen[2]["messages"] == seen[0]["messages"]
