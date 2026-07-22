"""Discover custom LangChain tools from modules and Python entry points."""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any

from langchain_core.tools import BaseTool

from core.tool_config import CustomToolManifest, CustomToolsConfig
from core.tool_runtime import (
    ToolCatalog,
    ToolDescriptor,
    ToolRisk,
    ToolLockScope,
    ToolRetryPolicy,
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


def _descriptor(tool: BaseTool, provider: str, manifest: CustomToolManifest) -> ToolDescriptor:
    return ToolDescriptor(
        name=tool.name,
        description=tool.description or tool.name,
        source=ToolSource.CUSTOM,
        provider=provider,
        provider_id=manifest.id,
        version=manifest.version,
        category=manifest.category,
        prompt_priority=manifest.prompt_priority,
        scopes=frozenset(manifest.scopes),
        capabilities=frozenset({f"custom.{tool.name}", *manifest.capabilities}),
        risk=manifest.risk,
        read_only=bool(getattr(tool, "read_only", False)),
        idempotent=bool(getattr(tool, "idempotent", False)),
        concurrency_safe=bool(getattr(tool, "concurrency_safe", False)),
        exclusive=bool(getattr(tool, "exclusive", False)),
        lock_scope=ToolLockScope(getattr(tool, "lock_scope", "none")),
        timeout_s=float(getattr(tool, "timeout_s", 30.0)),
        max_concurrency=int(getattr(tool, "max_concurrency", 0)),
        retry=ToolRetryPolicy.model_validate(
            getattr(tool, "retry_policy", {"max_attempts": 1})
        ),
        factory=lambda tool=tool: tool.model_copy(deep=True),
    )


def _resolve_manifest(
    provider_name: str,
    provider: Any,
    configured: CustomToolsConfig,
    module_manifest: Any = None,
) -> CustomToolManifest:
    manifest = configured.manifests.get(provider_name)
    if manifest is not None:
        return manifest
    raw = module_manifest if module_manifest is not None else getattr(provider, "TOOL_MANIFEST", None)
    if raw is None:
        raise ValueError(
            f"custom tool provider {provider_name!r} must declare TOOL_MANIFEST "
            "or be configured under tools.custom.manifests"
        )
    return CustomToolManifest.model_validate(raw)


def _apply_manifest(
    value: BaseTool | ToolDescriptor,
    provider: str,
    manifest: CustomToolManifest,
) -> ToolDescriptor:
    if isinstance(value, BaseTool):
        return _descriptor(value, provider, manifest)
    if value.source != ToolSource.CUSTOM:
        raise ValueError(f"custom provider {provider!r} returned non-custom descriptor")
    if manifest.category == "nlp" and not value.name.startswith("nlp_"):
        raise ValueError("NLP custom tools must use the nlp_ namespace")
    return value.model_copy(
        update={
            "provider": provider,
            "provider_id": manifest.id,
            "version": manifest.version,
            "category": manifest.category,
            "prompt_priority": manifest.prompt_priority,
            "scopes": frozenset(manifest.scopes),
            "capabilities": frozenset({f"custom.{value.name}", *manifest.capabilities, *value.capabilities}),
            "risk": manifest.risk,
        }
    )


def load_custom_tools(config: CustomToolsConfig, catalog: ToolCatalog) -> list[str]:
    providers: list[tuple[str, Any, Any]] = []
    for module_name in config.modules:
        module = importlib.import_module(module_name)
        provider = getattr(module, "TOOLS", None) or getattr(module, "get_tools", None)
        if provider is None:
            raise ValueError(f"custom tool module {module_name!r} must expose TOOLS or get_tools")
        providers.append((module_name, provider, getattr(module, "TOOL_MANIFEST", None)))

    for entrypoint in entry_points(group=config.entrypoint_group):
        provider = entrypoint.load()
        providers.append((f"entrypoint:{entrypoint.name}", provider, getattr(provider, "TOOL_MANIFEST", None)))

    registered: list[str] = []
    for provider_name, provider, module_manifest in providers:
        manifest = _resolve_manifest(provider_name, provider, config, module_manifest)
        if not manifest.enabled:
            logger.info("Custom tool provider disabled by manifest", provider=provider_name)
            continue
        for value in _flatten_tools(provider):
            descriptor = _apply_manifest(value, provider_name, manifest)
            catalog.register(descriptor)
            registered.append(descriptor.name)
    logger.info("Custom tools loaded", count=len(registered), tools=registered)
    return registered
