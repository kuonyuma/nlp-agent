"""Compatibility facade over the unified tool catalog and capability policy."""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool

from core.custom_tools import load_custom_tools
from core.tool_config import AgentRuntimeConfig, load_agent_runtime_config
from core.tool_runtime import (
    ToolDescriptor,
    ToolGrantRequest,
    ToolGrantSnapshot,
    ToolRisk,
    ToolScope,
    ToolSet,
    ToolSource,
    global_tool_runtime,
)
from server.tools.tool_manager import register_builtin_tools
from utils.logger import get_logger


logger = get_logger("nlp_agent.tools")


class PhysicalToolManager:
    """Build role-scoped ToolSets from one catalog; no parallel registries."""

    def __init__(self) -> None:
        self.runtime = global_tool_runtime
        self.config: AgentRuntimeConfig = load_agent_runtime_config()
        self._extensions_loaded = False
        register_builtin_tools(self.runtime.catalog)

    @property
    def catalog_revision(self) -> int:
        return self.runtime.catalog.revision

    def refresh_config(self) -> None:
        self.config = load_agent_runtime_config()

    async def start_extensions(self) -> None:
        if not self._extensions_loaded:
            load_custom_tools(self.config.tools.custom, self.runtime.catalog)
            self._extensions_loaded = True
        await self.runtime.start_mcp(self.config.tools.mcp_servers)

    async def close(self) -> None:
        await self.runtime.close()

    def register_tool(
        self,
        tool: BaseTool,
        *,
        source: ToolSource,
        provider: str,
        scopes: Iterable[ToolScope],
        capabilities: Iterable[str],
        risk: ToolRisk = ToolRisk.LOW,
        read_only: bool = False,
        concurrency_safe: bool = False,
        exclusive: bool = False,
        timeout_s: float = 30.0,
    ) -> None:
        descriptor = ToolDescriptor(
            name=tool.name,
            description=tool.description or tool.name,
            source=source,
            provider=provider,
            scopes=frozenset(scopes),
            capabilities=frozenset(capabilities),
            risk=risk,
            read_only=read_only,
            concurrency_safe=concurrency_safe,
            exclusive=exclusive,
            timeout_s=timeout_s,
            factory=(
                (lambda tool=tool: tool)
                if source == ToolSource.ORCHESTRATION
                else (lambda tool=tool: tool.model_copy(deep=True))
            ),
        )
        self.runtime.catalog.register(descriptor)

    def register_orchestration_tool(
        self,
        tool: BaseTool,
        *,
        capability: str = "runtime.control",
        risk: ToolRisk = ToolRisk.MEDIUM,
    ) -> None:
        existing = self.runtime.catalog.get(tool.name)
        if existing is not None:
            if existing.source != ToolSource.ORCHESTRATION:
                raise ValueError(f"orchestration tool collision: {tool.name}")
            return
        self.register_tool(
            tool,
            source=ToolSource.ORCHESTRATION,
            provider="coordinator",
            scopes={ToolScope.COORDINATOR},
            capabilities={capability},
            risk=risk,
            timeout_s=600,
        )

    def register_mcp_tool(self, tool: BaseTool, *, server: str = "manual") -> None:
        """Compatibility entry point; managed MCP should use MCPRuntime discovery."""
        self.register_tool(
            tool,
            source=ToolSource.MCP,
            provider=server,
            scopes={ToolScope.WORKER},
            capabilities={f"mcp.{server}.{tool.name}"},
            risk=ToolRisk.MEDIUM,
            timeout_s=30,
        )

    def get_coordinator_toolset(
        self,
        orchestration_tools: Iterable[BaseTool],
        *,
        session_id: str = "",
    ) -> ToolSet:
        for tool in orchestration_tools:
            capability = "worker.manage" if tool.name in {"spawn_worker", "send_message", "TaskStop"} else "runtime.control"
            self.register_orchestration_tool(tool, capability=capability)
        policy = self.config.tools.policies.coordinator
        return self.runtime.build_toolset(
            ToolGrantRequest(
                role=ToolScope.COORDINATOR,
                session_id=session_id,
                allowed_tools=frozenset(policy.allowed_tools),
                allowed_capabilities=frozenset(policy.allowed_capabilities),
                denied_tools=frozenset(policy.denied_tools),
                denied_capabilities=frozenset(policy.denied_capabilities),
            )
        )

    def get_worker_toolset(
        self,
        *,
        allowed_names: Iterable[str] = (),
        capabilities: Iterable[str] = (),
        denied_names: Iterable[str] = (),
        session_id: str = "",
        profile: str = "",
    ) -> ToolSet:
        policy = self.config.tools.policies.worker
        return self.runtime.build_toolset(
            ToolGrantRequest(
                role=ToolScope.WORKER,
                session_id=session_id,
                profile=profile,
                allowed_tools=frozenset({*policy.allowed_tools, *allowed_names}),
                allowed_capabilities=frozenset(
                    {*policy.allowed_capabilities, *capabilities}
                ),
                denied_tools=frozenset({*policy.denied_tools, *denied_names}),
                denied_capabilities=frozenset(policy.denied_capabilities),
            )
        )

    def get_worker_toolset_from_snapshot(
        self,
        snapshot: ToolGrantSnapshot,
    ) -> ToolSet:
        if snapshot.role != ToolScope.WORKER:
            raise ValueError("only Worker grants can be restored for a Worker")
        return self.runtime.restore_toolset(snapshot)

    def get_worker_tools(self, allowed_names: list[str]) -> list[BaseTool]:
        """Legacy adapter for callers that have not migrated to ToolSet yet."""
        return self.get_worker_toolset(allowed_names=allowed_names).tools

    def get_coordinator_tools(self, orchestration_tools: list[BaseTool]) -> list[BaseTool]:
        return self.get_coordinator_toolset(orchestration_tools).tools

    def has_tool(self, name: str) -> bool:
        return self.runtime.catalog.get(name) is not None


physical_tool_manager = PhysicalToolManager()
