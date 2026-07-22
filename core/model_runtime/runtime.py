"""Bounded retry, timeout, circuit breaking, failover, and streaming semantics."""

from __future__ import annotations

import asyncio
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, message_chunk_to_message

from core.model_runtime.contracts import (
    CircuitBreakerPolicy,
    ModelDefinition,
    ModelPresetConfig,
)
from core.model_runtime.normalization import normalize_chunk, normalize_message, response_usage
from core.observability.context import current_telemetry_context
from core.observability.models import SpanKind
from core.observability.runtime import global_telemetry
from utils.logger import get_logger


logger = get_logger("nlp_agent.model_runtime")


class ModelRuntimeExhaustedError(RuntimeError):
    pass


class EmptyModelResponseError(RuntimeError):
    pass


class StreamInterruptedError(RuntimeError):
    """A stream failed after externally visible output; transparent replay is unsafe."""

    def __init__(self, message: str, *, provider: str, model: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


@dataclass
class CircuitState:
    failures: int = 0
    open_until: float = 0.0

    def available(self) -> bool:
        return time.monotonic() >= self.open_until

    def succeed(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def fail(self, policy: CircuitBreakerPolicy) -> None:
        self.failures += 1
        if self.failures >= policy.failure_threshold:
            self.open_until = time.monotonic() + policy.cooldown_s


@dataclass
class ModelCandidate:
    preset_name: str
    provider_name: str
    model_name: str
    definition: ModelDefinition
    preset: ModelPresetConfig
    model: Any
    circuit: CircuitState = field(default_factory=CircuitState)


@dataclass(frozen=True)
class ErrorDecision:
    retryable: bool
    kind: str
    retry_after_s: float | None = None


def classify_model_error(error: BaseException) -> ErrorDecision:
    if isinstance(error, EmptyModelResponseError):
        return ErrorDecision(True, "empty_response")
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return ErrorDecision(True, "timeout")
    status = getattr(error, "status_code", None)
    message = str(error).lower()
    code = str(getattr(error, "code", "") or "").lower()
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        details = body.get("error", body)
        code = str(details.get("code", code) or code).lower()
        message = f"{message} {details.get('type', '')} {details.get('message', '')}".lower()
    quota_markers = (
        "insufficient_quota", "quota_exceeded", "insufficient balance",
        "payment_required", "out of credits", "billing",
    )
    if any(marker in f"{code} {message}" for marker in quota_markers):
        return ErrorDecision(False, "quota")
    retry_after = None
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        try:
            retry_after = max(0.0, float(headers.get("retry-after")))
        except (TypeError, ValueError):
            retry_after = None
    if status in {408, 409, 429} or (isinstance(status, int) and status >= 500):
        return ErrorDecision(True, f"http_{status}", retry_after)
    if status in {400, 401, 403, 404, 422}:
        kind = "context_length" if "context" in message and "length" in message else f"http_{status}"
        return ErrorDecision(False, kind)
    transient = ("timeout", "timed out", "connection", "reset", "overloaded", "temporarily unavailable")
    if any(marker in message for marker in transient):
        return ErrorDecision(True, "connection")
    return ErrorDecision(False, type(error).__name__)


@asynccontextmanager
async def _attempt_span(candidate: ModelCandidate, attempt: int, fallback_index: int):
    context = current_telemetry_context()
    if context is None:
        yield None
        return
    async with global_telemetry.span(
        SpanKind.MODEL,
        "model.request",
        context=context,
        attempt=attempt,
        attributes={
            "provider": candidate.provider_name,
            "model": candidate.definition.model_id,
            "preset": candidate.preset_name,
            "fallback_index": fallback_index,
            "thinking_enabled": candidate.preset.thinking.enabled,
            "reasoning_effort": candidate.preset.thinking.effort.value,
        },
    ) as span:
        yield span


class ResilientChatModel:
    """LangChain-compatible facade over a capability-compatible candidate chain."""

    emits_model_telemetry = True

    def __init__(self, candidates: list[ModelCandidate], *, normalize_response: bool = True) -> None:
        if not candidates:
            raise ValueError("At least one model candidate is required")
        self.candidates = candidates
        self.normalize_response = normalize_response
        self.model_name = candidates[0].definition.model_id
        self.context_window_tokens = min(
            candidate.definition.context_window_tokens for candidate in candidates
        )
        self.max_output_tokens = max(
            candidate.preset.generation.max_output_tokens for candidate in candidates
        )

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "ResilientChatModel":
        return ResilientChatModel([
            ModelCandidate(
                preset_name=item.preset_name,
                provider_name=item.provider_name,
                model_name=item.model_name,
                definition=item.definition,
                preset=item.preset,
                model=item.model.bind_tools(tools, **kwargs),
                circuit=item.circuit,
            )
            for item in self.candidates
        ], normalize_response=self.normalize_response)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "ResilientChatModel":
        return ResilientChatModel([
            ModelCandidate(
                preset_name=item.preset_name,
                provider_name=item.provider_name,
                model_name=item.model_name,
                definition=item.definition,
                preset=item.preset,
                model=item.model.with_structured_output(schema, **kwargs),
                circuit=item.circuit,
            )
            for item in self.candidates
        ], normalize_response=False)

    @staticmethod
    def _delay(candidate: ModelCandidate, attempt: int, decision: ErrorDecision) -> float:
        if decision.retry_after_s is not None:
            return min(candidate.preset.retry.max_delay_s, decision.retry_after_s)
        cap = min(
            candidate.preset.retry.max_delay_s,
            candidate.preset.retry.base_delay_s * (2 ** max(0, attempt - 1)),
        )
        return random.uniform(0, cap) if candidate.preset.retry.jitter == "full" else cap

    @staticmethod
    def _visible_chunk(chunk: Any) -> bool:
        if getattr(chunk, "content", None):
            return True
        if getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None):
            return True
        additional = getattr(chunk, "additional_kwargs", None) or {}
        return bool(additional.get("reasoning_content"))

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if self.normalize_response:
            combined: Any = None
            async for chunk in self.astream(input, config=config, **kwargs):
                combined = chunk if combined is None else combined + chunk
            if combined is None:
                raise ModelRuntimeExhaustedError("Model stream completed without a response")
            message = (
                message_chunk_to_message(combined)
                if isinstance(combined, AIMessageChunk)
                else combined
            )
            if not isinstance(message, AIMessage):
                raise TypeError(f"Provider returned {type(message).__name__}, expected AIMessage")
            return normalize_message(message)

        last_error: BaseException | None = None
        for fallback_index, candidate in enumerate(self.candidates):
            if not candidate.circuit.available():
                global_telemetry.event("model.circuit_open", level="warning", payload={
                    "provider": candidate.provider_name, "model": candidate.definition.model_id,
                    "preset": candidate.preset_name,
                })
                continue
            for attempt in range(1, candidate.preset.retry.max_attempts + 1):
                try:
                    async with _attempt_span(candidate, attempt, fallback_index) as span:
                        response = await asyncio.wait_for(
                            candidate.model.ainvoke(input, config=config, **kwargs),
                            timeout=candidate.preset.timeouts.total_s,
                        )
                        if self.normalize_response and not isinstance(response, AIMessage):
                            raise TypeError(f"Provider returned {type(response).__name__}, expected AIMessage")
                        normalized = normalize_message(response) if isinstance(response, AIMessage) else response
                        if span is not None:
                            if isinstance(normalized, AIMessage):
                                usage = response_usage(normalized)
                                span.set_usage(usage)
                                span.annotate(
                                    finish_reason=normalized.response_metadata.get("finish_reason", ""),
                                    cache_read_tokens=usage["prompt_cache_hit_tokens"],
                                    cache_miss_tokens=usage["prompt_cache_miss_tokens"],
                                )
                            else:
                                span.annotate(structured_output=True)
                    candidate.circuit.succeed()
                    return normalized
                except asyncio.CancelledError:
                    raise
                except BaseException as error:
                    last_error = error
                    decision = classify_model_error(error)
                    candidate.circuit.fail(candidate.preset.circuit_breaker)
                    if not decision.retryable:
                        raise
                    if attempt < candidate.preset.retry.max_attempts:
                        delay = self._delay(candidate, attempt, decision)
                        global_telemetry.event("model.retry", level="warning", payload={
                            "provider": candidate.provider_name,
                            "model": candidate.definition.model_id,
                            "attempt": attempt,
                            "error_kind": decision.kind,
                            "delay_s": delay,
                        })
                        await asyncio.sleep(delay)
            if fallback_index + 1 < len(self.candidates):
                global_telemetry.event("model.failover", level="warning", payload={
                    "from_provider": candidate.provider_name,
                    "from_model": candidate.definition.model_id,
                    "to_model": self.candidates[fallback_index + 1].definition.model_id,
                    "error_kind": classify_model_error(last_error).kind if last_error else "circuit_open",
                })
        raise ModelRuntimeExhaustedError("All configured model candidates failed") from last_error

    async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        last_error: BaseException | None = None
        for fallback_index, candidate in enumerate(self.candidates):
            if not candidate.circuit.available():
                continue
            for attempt in range(1, candidate.preset.retry.max_attempts + 1):
                received = False
                visible = False
                first = True
                started = time.monotonic()
                try:
                    async with _attempt_span(candidate, attempt, fallback_index) as span:
                        iterator = candidate.model.astream(input, config=config, **kwargs).__aiter__()
                        while True:
                            remaining_total = candidate.preset.timeouts.total_s - (time.monotonic() - started)
                            if remaining_total <= 0:
                                raise asyncio.TimeoutError("model stream total timeout")
                            wait_s = min(
                                remaining_total,
                                candidate.preset.timeouts.first_token_s if first
                                else candidate.preset.timeouts.stream_idle_s,
                            )
                            try:
                                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=wait_s)
                            except StopAsyncIteration:
                                break
                            first = False
                            received = True
                            visible = visible or self._visible_chunk(chunk)
                            normalized = normalize_chunk(chunk) if isinstance(chunk, AIMessageChunk) else chunk
                            if span is not None:
                                if "ttft_ms" not in span.attributes:
                                    span.annotate(ttft_ms=max(0, int((time.monotonic() - started) * 1000)))
                                usage = response_usage(normalized)
                                if usage["total_tokens"]:
                                    span.set_usage(usage)
                            yield normalized
                        if not received:
                            raise EmptyModelResponseError("Provider stream completed without chunks")
                    candidate.circuit.succeed()
                    return
                except asyncio.CancelledError:
                    raise
                except BaseException as error:
                    last_error = error
                    decision = classify_model_error(error)
                    candidate.circuit.fail(candidate.preset.circuit_breaker)
                    if visible:
                        global_telemetry.event("model.stream_interrupted", level="error", payload={
                            "provider": candidate.provider_name,
                            "model": candidate.definition.model_id,
                            "error_kind": decision.kind,
                        })
                        raise StreamInterruptedError(
                            "Model stream interrupted after visible output",
                            provider=candidate.provider_name,
                            model=candidate.definition.model_id,
                        ) from error
                    if not decision.retryable:
                        raise
                    if attempt < candidate.preset.retry.max_attempts:
                        await asyncio.sleep(self._delay(candidate, attempt, decision))
            if fallback_index + 1 < len(self.candidates):
                global_telemetry.event("model.failover", level="warning", payload={
                    "from_model": candidate.definition.model_id,
                    "to_model": self.candidates[fallback_index + 1].definition.model_id,
                    "streaming": True,
                })
        raise ModelRuntimeExhaustedError("All configured streaming model candidates failed") from last_error
