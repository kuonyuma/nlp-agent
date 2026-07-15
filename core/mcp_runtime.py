"""Managed MCP clients exposed through the unified tool catalog."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from langchain_core.tools import StructuredTool

from core.tool_config import MCPServerConfig
from core.tool_runtime import (
    ToolCatalog,
    ToolDescriptor,
    ToolRisk,
    ToolSource,
)
from utils.logger import get_logger


logger = get_logger("nlp_agent.mcp")
_INVALID_NAME = re.compile(r"[^a-zA-Z0-9_-]+")


def mcp_tool_name(server: str, raw_name: str) -> str:
    base = _INVALID_NAME.sub("_", f"mcp_{server}_{raw_name}").strip("_") or "mcp_tool"
    if len(base) <= 64:
        return base
    digest = hashlib.sha256(base.encode()).hexdigest()[:8]
    return f"{base[:55]}_{digest}"


def _render_content(result: Any) -> str:
    if getattr(result, "isError", False):
        raise RuntimeError(_render_blocks(getattr(result, "content", [])))
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)
    return _render_blocks(getattr(result, "content", []))


def _render_blocks(blocks: list[Any]) -> str:
    output: list[str] = []
    for block in blocks:
        if hasattr(block, "text"):
            output.append(str(block.text))
        elif hasattr(block, "model_dump"):
            output.append(json.dumps(block.model_dump(mode="json"), ensure_ascii=False))
        else:
            output.append(str(block))
    return "\n".join(output)


async def validate_mcp_url(url: str, *, allow_private_network: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote MCP URL must use http/https and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("credentials must be supplied through MCP headers, not the URL")
    if allow_private_network:
        return
    try:
        addresses = {ipaddress.ip_address(parsed.hostname)}
    except ValueError:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        addresses = {ipaddress.ip_address(record[4][0]) for record in records}
    blocked = [
        address
        for address in addresses
        if address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ]
    if blocked:
        raise ValueError(
            "remote MCP URL resolves to a blocked private/special address; "
            "set allow_private_network=true only for a trusted server"
        )


@dataclass
class _Connection:
    config: MCPServerConfig
    stack: AsyncExitStack
    session: Any


class MCPRuntime:
    """Own MCP transports, discovery, namespacing, and reconnects."""

    def __init__(self, catalog: ToolCatalog) -> None:
        self.catalog = catalog
        self._connections: dict[str, _Connection] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def connect_all(self, configs: Mapping[str, Any]) -> None:
        validated = {
            name: config
            if isinstance(config, MCPServerConfig)
            else MCPServerConfig.model_validate(config)
            for name, config in configs.items()
        }
        removed = set(self._connections).difference(validated)
        for name in removed:
            await self._disconnect(name)
        for name, config in validated.items():
            current = self._connections.get(name)
            if current is not None and current.config == config:
                continue
            await self._connect(name, config)

    async def _connect(self, name: str, config: MCPServerConfig) -> None:
        async with self._locks.setdefault(name, asyncio.Lock()):
            await self._disconnect(name)
            if config.transport in {"sse", "streamable_http"}:
                await validate_mcp_url(
                    config.url, allow_private_network=config.allow_private_network
                )
            stack = AsyncExitStack()
            await stack.__aenter__()
            try:
                session = await self._open_session(stack, config)
                await asyncio.wait_for(session.initialize(), timeout=config.timeout_s)
                self._connections[name] = _Connection(config, stack, session)
                await self._discover(name, session, config)
                logger.info("MCP server connected", server=name)
            except Exception:
                await stack.aclose()
                self.catalog.unregister_provider(ToolSource.MCP, name)
                raise

    async def _open_session(self, stack: AsyncExitStack, config: MCPServerConfig) -> Any:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.sse import sse_client
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as error:
            raise RuntimeError("MCP support requires the 'mcp' package") from error

        if config.transport == "stdio":
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or None,
                cwd=config.cwd or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif config.transport == "sse":
            def factory(**kwargs: Any) -> httpx.AsyncClient:
                headers = {**config.headers, **(kwargs.get("headers") or {})}
                return httpx.AsyncClient(
                    headers=headers or None,
                    follow_redirects=True,
                    timeout=kwargs.get("timeout"),
                    auth=kwargs.get("auth"),
                )

            read, write = await stack.enter_async_context(
                sse_client(config.url, httpx_client_factory=factory)
            )
        else:
            client = await stack.enter_async_context(
                httpx.AsyncClient(headers=config.headers or None, follow_redirects=True)
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(config.url, http_client=client)
            )
        return await stack.enter_async_context(ClientSession(read, write))

    async def _discover(self, server: str, session: Any, config: MCPServerConfig) -> None:
        discovered = await asyncio.wait_for(session.list_tools(), timeout=config.timeout_s)
        enabled = set(config.enabled_tools)
        allow_all = "*" in enabled
        matched: set[str] = set()
        for definition in discovered.tools:
            wrapped = mcp_tool_name(server, definition.name)
            if not allow_all and definition.name not in enabled and wrapped not in enabled:
                continue
            matched.update({definition.name, wrapped}.intersection(enabled))
            self._register_tool(server, definition, config)
        unmatched = enabled.difference({"*"}).difference(matched)
        if unmatched:
            raise ValueError(
                f"MCP server {server!r} enabled_tools not found: {', '.join(sorted(unmatched))}"
            )

    def _register_tool(self, server: str, definition: Any, config: MCPServerConfig) -> None:
        name = mcp_tool_name(server, definition.name)
        schema = definition.inputSchema or {"type": "object", "properties": {}}

        async def invoke(**arguments: Any) -> str:
            return await self.call_tool(server, definition.name, arguments)

        def factory() -> StructuredTool:
            return StructuredTool.from_function(
                coroutine=invoke,
                name=name,
                description=definition.description or definition.name,
                args_schema=schema,
                infer_schema=False,
            )

        self.catalog.register(
            ToolDescriptor(
                name=name,
                description=definition.description or definition.name,
                source=ToolSource.MCP,
                provider=server,
                scopes=frozenset(config.scopes),
                capabilities=frozenset({f"mcp.{server}.{definition.name}"}),
                risk=ToolRisk.MEDIUM,
                timeout_s=config.timeout_s,
                factory=factory,
            )
        )

    async def call_tool(self, server: str, raw_name: str, arguments: dict[str, Any]) -> str:
        connection = self._connections.get(server)
        if connection is None:
            raise RuntimeError(f"MCP server {server!r} is not connected")
        try:
            result = await asyncio.wait_for(
                connection.session.call_tool(raw_name, arguments),
                timeout=connection.config.timeout_s,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            config = connection.config
            await self._connect(server, config)
            result = await asyncio.wait_for(
                self._connections[server].session.call_tool(raw_name, arguments),
                timeout=config.timeout_s,
            )
        return _render_content(result)

    async def _disconnect(self, server: str) -> None:
        connection = self._connections.pop(server, None)
        self.catalog.unregister_provider(ToolSource.MCP, server)
        if connection is not None:
            try:
                await connection.stack.aclose()
            except Exception as error:
                logger.warning("MCP server close failed", server=server, error=str(error))

    async def close(self) -> None:
        for server in list(self._connections):
            await self._disconnect(server)
