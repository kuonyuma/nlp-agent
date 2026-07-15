"""Discover custom LangChain tools from modules and Python entry points."""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any

from langchain_core.tools import BaseTool

from core.tool_config import CustomToolsConfig
from core.tool_runtime import (
    ToolCatalog,
    ToolDescriptor,
    ToolRisk,
    ToolScope,
    ToolSource,
)
from utils.logger import get_logger


logger = get_logger("nlp_agent.custom_tools")


def _flatten_tools(value: Any) -> list[BaseTool | ToolDescriptor]:
    if isinstance(value, (BaseTool, ToolDescriptor)):
        return [value]
    if callable(value):
        return _flatten_tools(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        tools: list[BaseTool | ToolDescriptor] = []
        for item in value:
            tools.extend(_flatten_tools(item))
        return tools
    raise TypeError(f"custom tool provider returned unsupported value: {type(value).__name__}")


def _descriptor(tool: BaseTool, provider: str) -> ToolDescriptor:
    return ToolDescriptor(
        name=tool.name,
        description=tool.description or tool.name,
        source=ToolSource.CUSTOM,
        provider=provider,
        scopes=frozenset({ToolScope.WORKER}),
        capabilities=frozenset({f"custom.{tool.name}"}),
        risk=ToolRisk.MEDIUM,
        read_only=bool(getattr(tool, "read_only", False)),
        concurrency_safe=bool(getattr(tool, "concurrency_safe", False)),
        exclusive=bool(getattr(tool, "exclusive", False)),
        timeout_s=float(getattr(tool, "timeout_s", 30.0)),
        factory=lambda tool=tool: tool.model_copy(deep=True),
    )


def load_custom_tools(config: CustomToolsConfig, catalog: ToolCatalog) -> list[str]:
    providers: list[tuple[str, Any]] = []
    for module_name in config.modules:
        module = importlib.import_module(module_name)
        provider = getattr(module, "TOOLS", None) or getattr(module, "get_tools", None)
        if provider is None:
            raise ValueError(f"custom tool module {module_name!r} must expose TOOLS or get_tools")
        providers.append((module_name, provider))

    for entrypoint in entry_points(group=config.entrypoint_group):
        providers.append((f"entrypoint:{entrypoint.name}", entrypoint.load()))

    registered: list[str] = []
    for provider_name, provider in providers:
        for value in _flatten_tools(provider):
            descriptor = value if isinstance(value, ToolDescriptor) else _descriptor(value, provider_name)
            if descriptor.source != ToolSource.CUSTOM:
                raise ValueError(f"custom provider {provider_name!r} returned non-custom descriptor")
            catalog.register(descriptor)
            registered.append(descriptor.name)
    logger.info("Custom tools loaded", count=len(registered), tools=registered)
    return registered
