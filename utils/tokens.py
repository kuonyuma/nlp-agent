"""Deterministic model-input token estimation and budget calculation."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


class ContextBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_window: int = Field(gt=0)
    output_reserve: int = Field(default=16_000, ge=0)
    safety_margin: int = Field(default=2_000, ge=0)
    tool_schema_tokens: int = Field(default=0, ge=0)

    @property
    def input_limit(self) -> int:
        return max(
            1,
            self.context_window
            - self.output_reserve
            - self.safety_margin
            - self.tool_schema_tokens,
        )

    def threshold(self, ratio: float) -> int:
        return max(1, int(self.input_limit * ratio))


def get_token_count_from_usage(usage: Mapping[str, Any]) -> int:
    """Return input tokens when available; total_tokens is only a last fallback."""
    for key in ("input_tokens", "prompt_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
    value = usage.get("total_tokens", 0)
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


def _stable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return str(value)


def rough_token_count_estimation(content: Any) -> int:
    """Conservative mixed-language estimate, including JSON punctuation overhead."""
    text = _stable_text(content)
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    non_cjk = len(text) - cjk
    # Most modern tokenizers are close to one token per CJK character and
    # 3.5-4 Latin characters per token. A 10% margin avoids late compaction.
    return max(1, math.ceil((cjk * 1.05 + non_cjk / 3.6) * 1.10))


def _message_payload(message: Any) -> dict[str, Any]:
    if isinstance(message, Mapping):
        return dict(message)
    payload: dict[str, Any] = {
        "role": getattr(message, "type", message.__class__.__name__),
        "content": getattr(message, "content", ""),
    }
    for name in (
        "tool_calls",
        "toolCalls",
        "toolResult",
        "tool_call_id",
        "name",
        "artifact",
        "additional_kwargs",
    ):
        value = getattr(message, name, None)
        if value:
            payload[name] = value
    return payload


def estimate_message_tokens(message: Any) -> int:
    # Per-message/role framing overhead is provider-dependent; 6 is a safe
    # cross-provider approximation and prevents many tiny messages being free.
    return 6 + rough_token_count_estimation(_message_payload(message))


def rough_estimation_for_messages(messages: Iterable[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def token_count_with_estimation(
    messages: list[Any], original_messages: list[Any] | None = None
) -> int:
    """Estimate the current view itself; never reuse stale request usage totals."""
    del original_messages
    return rough_estimation_for_messages(messages)


def estimate_tool_schema_tokens(tools: Iterable[Any]) -> int:
    total = 0
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema = schema.model_json_schema()
        payload = {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
            "parameters": schema or {},
        }
        total += rough_token_count_estimation(payload) + 8
    return total


def build_context_budget(
    *,
    context_window: int,
    output_reserve: int,
    tools: Iterable[Any] = (),
    safety_margin: int = 2_000,
) -> ContextBudget:
    return ContextBudget(
        context_window=context_window,
        output_reserve=output_reserve,
        safety_margin=safety_margin,
        tool_schema_tokens=estimate_tool_schema_tokens(tools),
    )
