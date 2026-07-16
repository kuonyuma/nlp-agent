import asyncio

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.mcp_runtime import mcp_tool_name, validate_mcp_url
from core.tool_runtime import (
    ToolCatalog,
    ToolDescriptor,
    ToolGrantRequest,
    ToolRisk,
    ToolRuntime,
    ToolScope,
    ToolSource,
)
from server.tools.runtime_tool_node import RuntimeToolNode


class AddInput(BaseModel):
    left: int = Field(ge=0)
    right: int = Field(ge=0)


async def add(left: int, right: int) -> int:
    return left + right


def descriptor(*, name="add", scopes=None, capabilities=None, timeout_s=1.0):
    def factory():
        return StructuredTool.from_function(
            coroutine=add,
            name=name,
            description="Add non-negative integers",
            args_schema=AddInput,
        )

    return ToolDescriptor(
        name=name,
        description="Add non-negative integers",
        source=ToolSource.BUILTIN,
        scopes=frozenset(scopes or {ToolScope.WORKER}),
        capabilities=frozenset(capabilities or {"math.read"}),
        risk=ToolRisk.LOW,
        read_only=True,
        concurrency_safe=True,
        timeout_s=timeout_s,
        factory=factory,
    )


def test_catalog_rejects_collisions_and_policy_is_role_scoped():
    runtime = ToolRuntime()
    runtime.catalog.register(descriptor())
    with pytest.raises(ValueError, match="collision"):
        runtime.catalog.register(descriptor())

    worker = runtime.build_toolset(
        ToolGrantRequest(role=ToolScope.WORKER, allowed_capabilities={"math.read"})
    )
    coordinator = runtime.build_toolset(
        ToolGrantRequest(role=ToolScope.COORDINATOR, allowed_capabilities={"math.read"})
    )
    assert worker.names == ("add",)
    assert coordinator.names == ()


def test_policy_rejects_unknown_tools_instead_of_silently_dropping_them():
    runtime = ToolRuntime()
    with pytest.raises(ValueError, match="unknown tools"):
        runtime.build_toolset(
            ToolGrantRequest(role=ToolScope.WORKER, allowed_tools={"missing"})
        )


@pytest.mark.asyncio
async def test_executor_uses_pydantic_v2_and_structured_errors():
    runtime = ToolRuntime()
    runtime.catalog.register(descriptor())
    tools = runtime.build_toolset(
        ToolGrantRequest(role=ToolScope.WORKER, allowed_tools={"add"})
    )
    success = await tools.execute("add", {"left": 1, "right": 2})
    invalid = await tools.execute("add", {"left": -1, "right": 2})
    denied = await tools.execute("missing", {})
    assert success.ok and success.output == 3
    assert invalid.error and invalid.error.kind == "validation"
    assert denied.error and denied.error.kind == "permission_denied"


@pytest.mark.asyncio
async def test_runtime_node_executes_the_same_granted_toolset(monkeypatch):
    runtime = ToolRuntime()
    runtime.catalog.register(descriptor())
    tools = runtime.build_toolset(
        ToolGrantRequest(role=ToolScope.WORKER, allowed_tools={"add"})
    )
    monkeypatch.setattr(
        "server.tools.runtime_tool_node.persist_tool_messages",
        lambda messages, _config: messages,
    )
    node = RuntimeToolNode(lambda _config: tools)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"left": 2, "right": 4}, "id": "c1"}],
            )
        ]
    }
    output = await node(state, {})
    assert output["messages"][0].content == "6"
    assert output["messages"][0].status == "success"


def test_mcp_names_are_namespaced_stable_and_provider_safe():
    short = mcp_tool_name("github", "search/issues")
    long = mcp_tool_name("very-long-server-" * 8, "very-long-tool-" * 8)
    assert short == "mcp_github_search_issues"
    assert len(long) <= 64
    assert long == mcp_tool_name("very-long-server-" * 8, "very-long-tool-" * 8)


@pytest.mark.asyncio
async def test_remote_mcp_blocks_private_network_by_default():
    with pytest.raises(ValueError, match="blocked private"):
        await validate_mcp_url("http://127.0.0.1:9000/mcp")
    await validate_mcp_url(
        "http://127.0.0.1:9000/mcp", allow_private_network=True
    )


def test_persisted_grant_restores_exact_tools_without_policy_expansion():
    runtime = ToolRuntime()
    runtime.catalog.register(descriptor(name="add"))
    runtime.catalog.register(descriptor(name="sum_more"))
    original = runtime.build_toolset(
        ToolGrantRequest(role=ToolScope.WORKER, allowed_tools={"add"})
    )
    restored = runtime.restore_toolset(original.snapshot)
    assert restored.names == ("add",)
