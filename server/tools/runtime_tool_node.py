"""LangGraph node backed by the exact ToolSet exposed to the Coordinator model."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from core.tool_runtime import ToolSet
from server.agent.compression.tool_persistence import persist_tool_messages


class RuntimeToolNode:
    def __init__(self, toolset_provider: Callable[[RunnableConfig], ToolSet]) -> None:
        self._toolset_provider = toolset_provider

    async def __call__(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}
        tool_calls = list(getattr(messages[-1], "tool_calls", None) or [])
        toolset = self._toolset_provider(config)
        results = await toolset.execute_many(
            [(call.get("name", ""), call.get("args", {})) for call in tool_calls],
            config,
        )
        output = [
            ToolMessage(
                content=result.to_model_content(),
                tool_call_id=call.get("id", ""),
                name=call.get("name", ""),
                status="success" if result.ok else "error",
                artifact=result.model_dump(),
            )
            for call, result in zip(tool_calls, results)
        ]
        return {"messages": persist_tool_messages(output, config)}
