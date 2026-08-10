"""Normalize provider response metadata without repairing executable tool arguments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk


def normalize_usage(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(metadata or {})
    input_details = {
        k: v
        for k, v in (
            raw.get("input_token_details") or raw.get("prompt_tokens_details") or {}
        ).items()
        if v is not None
    }
    output_details = {
        k: v
        for k, v in (
            raw.get("output_token_details") or raw.get("completion_tokens_details") or {}
        ).items()
        if v is not None
    }
    input_tokens = int(raw.get("input_tokens", raw.get("prompt_tokens", 0)) or 0)
    output_tokens = int(raw.get("output_tokens", raw.get("completion_tokens", 0)) or 0)
    cache_read = int(
        raw.get(
            "prompt_cache_hit_tokens",
            raw.get(
                "cached_tokens",
                raw.get(
                    "cache_read_input_tokens",
                    input_details.get("cache_read", input_details.get("cached_tokens", 0)),
                ),
            ),
        )
        or 0
    )
    cache_miss = int(raw.get("prompt_cache_miss_tokens", input_details.get("cache_miss", 0)) or 0)
    reasoning = int(
        raw.get(
            "reasoning_tokens",
            output_details.get("reasoning", output_details.get("reasoning_tokens", 0)),
        )
        or 0
    )
    total = int(raw.get("total_tokens", input_tokens + output_tokens) or 0)
    return {
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
        "total_tokens": max(0, total),
        "input_token_details": {
            **input_details,
            "cache_read": max(0, cache_read),
            "cache_miss": max(0, cache_miss),
        },
        "output_token_details": {
            **output_details,
            "reasoning": max(0, reasoning),
        },
        "prompt_cache_hit_tokens": max(0, cache_read),
        "prompt_cache_miss_tokens": max(0, cache_miss),
    }


def response_usage(message: Any) -> dict[str, Any]:
    direct = getattr(message, "usage_metadata", None)
    if direct:
        return normalize_usage(direct)
    response = getattr(message, "response_metadata", None) or {}
    return normalize_usage(response.get("token_usage") or response.get("usage") or {})


def normalize_message(message: AIMessage) -> AIMessage:
    usage = response_usage(message)
    response_metadata = dict(message.response_metadata or {})
    finish = response_metadata.get("finish_reason")
    if finish == "function_call":
        response_metadata["finish_reason"] = "tool_calls"
    updates: dict[str, Any] = {"response_metadata": response_metadata}
    if usage["total_tokens"] or usage["input_tokens"] or usage["output_tokens"]:
        updates["usage_metadata"] = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "input_token_details": usage["input_token_details"],
            "output_token_details": usage["output_token_details"],
        }
        updates["additional_kwargs"] = {
            **message.additional_kwargs,
            "provider_usage": usage,
        }
    return message.model_copy(update=updates)


def normalize_chunk(chunk: AIMessageChunk) -> AIMessageChunk:
    usage = response_usage(chunk)
    if not (usage["input_tokens"] or usage["output_tokens"] or usage["total_tokens"]):
        return chunk
    return chunk.model_copy(update={
        "usage_metadata": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "input_token_details": usage["input_token_details"],
            "output_token_details": usage["output_token_details"],
        },
        "additional_kwargs": {
            **chunk.additional_kwargs,
            "provider_usage": usage,
        },
    })
