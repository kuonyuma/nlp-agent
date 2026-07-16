import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.model_runtime.adapters.deepseek import DeepSeekChatModel
from core.model_runtime.contracts import (
    CircuitBreakerPolicy,
    GenerationConfig,
    ModelCapabilities,
    ModelDefinition,
    ModelPresetConfig,
    ModelRouteConfig,
    ModelRuntimeConfig,
    ProviderConfig,
    RetryPolicy,
    ThinkingConfig,
    TimeoutPolicy,
)
from core.model_runtime.normalization import normalize_usage
from core.model_runtime.runtime import (
    ModelCandidate,
    ResilientChatModel,
    StreamInterruptedError,
    classify_model_error,
)


def preset(*, attempts=1):
    return ModelPresetConfig(
        model="model",
        thinking=ThinkingConfig(enabled=False, effort="none"),
        generation=GenerationConfig(max_output_tokens=100),
        timeouts=TimeoutPolicy(connect_s=1, first_token_s=1, stream_idle_s=1, total_s=2),
        retry=RetryPolicy(max_attempts=attempts, base_delay_s=0, max_delay_s=0, jitter="none"),
        circuit_breaker=CircuitBreakerPolicy(failure_threshold=10, cooldown_s=1),
    )


def definition(model_id="model"):
    return ModelDefinition(
        provider="test", model_id=model_id,
        context_window_tokens=1000, max_output_tokens=100,
        capabilities=ModelCapabilities(thinking=True),
    )


def candidate(name, model, *, attempts=1):
    return ModelCandidate(
        preset_name=name, provider_name="test", model_name=name,
        definition=definition(name), preset=preset(attempts=attempts), model=model,
    )


class StatusError(RuntimeError):
    def __init__(self, status_code, message="failed"):
        super().__init__(message)
        self.status_code = status_code


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.bound_tools = None

    async def ainvoke(self, _input, config=None, **_kwargs):
        self.calls += 1
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def astream(self, input, config=None, **kwargs):
        yield await self.ainvoke(input, config=config, **kwargs)

    def bind_tools(self, tools, **_kwargs):
        self.bound_tools = tools
        return self

    def with_structured_output(self, _schema, **_kwargs):
        return self


class FakeStreamModel(FakeModel):
    def __init__(self, chunks):
        super().__init__([])
        self.chunks = chunks

    async def astream(self, _input, config=None, **_kwargs):
        self.calls += 1
        for value in self.chunks:
            if isinstance(value, BaseException):
                raise value
            yield value


def test_typed_config_rejects_incapable_fallback():
    with pytest.raises(ValueError, match="tool-call capability"):
        ModelRuntimeConfig(
            providers={"test": ProviderConfig(adapter="x", base_url="http://test", api_key_env="KEY")},
            models={
                "primary": ModelDefinition(
                    provider="test", model_id="primary", context_window_tokens=100,
                    max_output_tokens=10, capabilities=ModelCapabilities(tool_calls=True),
                ),
                "fallback": ModelDefinition(
                    provider="test", model_id="fallback", context_window_tokens=100,
                    max_output_tokens=10, capabilities=ModelCapabilities(tool_calls=False),
                ),
            },
            model_presets={
                "p": ModelPresetConfig(model="primary", generation=GenerationConfig(max_output_tokens=10)),
                "f": ModelPresetConfig(model="fallback", generation=GenerationConfig(max_output_tokens=10)),
            },
            model_routes={"coordinator": ModelRouteConfig(primary="p", fallbacks=("f",))},
        )


def test_deepseek_usage_normalization_includes_kv_cache():
    usage = normalize_usage({
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_cache_hit_tokens": 75,
        "prompt_cache_miss_tokens": 25,
    })
    assert usage["input_token_details"]["cache_read"] == 75
    assert usage["input_token_details"]["cache_miss"] == 25


def test_deepseek_replays_reasoning_only_for_tool_call_messages():
    model = DeepSeekChatModel(
        model="deepseek-v4-pro", api_base="https://api.deepseek.com",
        api_key="test", max_retries=0,
    )
    plain = AIMessage(content="answer", additional_kwargs={"reasoning_content": "private"})
    tool = AIMessage(
        content="", additional_kwargs={"reasoning_content": "needed"},
        tool_calls=[{"id": "call-1", "name": "lookup", "args": {"q": "x"}, "type": "tool_call"}],
    )
    payload = model._get_request_payload([
        HumanMessage(content="one"), plain, HumanMessage(content="two"), tool,
    ])
    assert "reasoning_content" not in payload["messages"][1]
    assert payload["messages"][3]["reasoning_content"] == "needed"


@pytest.mark.asyncio
async def test_transient_errors_retry_then_fail_over():
    primary = FakeModel([StatusError(503), StatusError(503)])
    fallback = FakeModel([AIMessage(content="ok", usage_metadata={
        "input_tokens": 2, "output_tokens": 1, "total_tokens": 3,
    })])
    runtime = ResilientChatModel([
        candidate("primary", primary, attempts=2),
        candidate("fallback", fallback),
    ])
    result = await runtime.ainvoke([HumanMessage(content="hello")])
    assert result.content == "ok"
    assert primary.calls == 2
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_non_retryable_error_does_not_fail_over():
    primary = FakeModel([StatusError(400, "invalid tool schema")])
    fallback = FakeModel([AIMessage(content="must not run")])
    runtime = ResilientChatModel([candidate("primary", primary), candidate("fallback", fallback)])
    with pytest.raises(StatusError):
        await runtime.ainvoke([HumanMessage(content="hello")])
    assert fallback.calls == 0
    assert not classify_model_error(StatusError(400)).retryable


@pytest.mark.asyncio
async def test_stream_can_fail_over_before_first_delta():
    primary = FakeStreamModel([StatusError(503)])
    fallback = FakeStreamModel([AIMessage(content="ok")])
    runtime = ResilientChatModel([candidate("primary", primary), candidate("fallback", fallback)])
    chunks = [chunk async for chunk in runtime.astream([HumanMessage(content="hello")])]
    assert chunks[0].content == "ok"


@pytest.mark.asyncio
async def test_stream_never_replays_after_visible_delta():
    primary = FakeStreamModel([AIMessage(content="partial"), StatusError(503)])
    fallback = FakeStreamModel([AIMessage(content="duplicate")])
    runtime = ResilientChatModel([candidate("primary", primary), candidate("fallback", fallback)])
    stream = runtime.astream([HumanMessage(content="hello")])
    first = await anext(stream)
    assert first.content == "partial"
    with pytest.raises(StreamInterruptedError):
        await anext(stream)
    assert fallback.calls == 0


def test_bind_tools_applies_to_every_fallback_candidate():
    first, second = FakeModel([]), FakeModel([])
    runtime = ResilientChatModel([candidate("one", first), candidate("two", second)])
    bound = runtime.bind_tools(["tool"])
    assert first.bound_tools == ["tool"]
    assert second.bound_tools == ["tool"]
    assert len(bound.candidates) == 2
