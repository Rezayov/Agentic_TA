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
    assert [r.name for r in loaded.providers] == ["gcat", "agentrouter", "dahl", "hormouz"]
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
    monkeypatch.setattr(provider_cli, "configure_logging", lambda path: None)
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
