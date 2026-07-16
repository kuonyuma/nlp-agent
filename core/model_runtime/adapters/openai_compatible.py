"""Generic explicit OpenAI Chat Completions adapter."""

from __future__ import annotations

from typing import Any

import httpx
from langchain_openai import ChatOpenAI

from core.model_runtime.contracts import ModelDefinition, ModelPresetConfig, ProviderConfig


class OpenAICompatibleAdapter:
    def build(
        self,
        *,
        provider_name: str,
        provider: ProviderConfig,
        model_name: str,
        model: ModelDefinition,
        preset_name: str,
        preset: ModelPresetConfig,
        api_key: str,
    ) -> ChatOpenAI:
        del provider_name, model_name, preset_name
        timeout = httpx.Timeout(preset.timeouts.total_s, connect=preset.timeouts.connect_s)
        kwargs: dict[str, Any] = {
            "model": model.model_id,
            "base_url": provider.base_url,
            "api_key": api_key,
            "max_tokens": preset.generation.max_output_tokens,
            "request_timeout": timeout,
            "stream_chunk_timeout": preset.timeouts.stream_idle_s,
            "stream_usage": True,
            "max_retries": 0,
            "default_headers": provider.default_headers or None,
        }
        if preset.generation.temperature is not None:
            kwargs["temperature"] = preset.generation.temperature
        if preset.generation.top_p is not None:
            kwargs["top_p"] = preset.generation.top_p
        if preset.thinking.enabled:
            kwargs["reasoning_effort"] = preset.thinking.effort.value
        return ChatOpenAI(**kwargs)
