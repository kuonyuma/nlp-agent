"""LangGraph node backed by the exact ToolSet exposed to the Coordinator model."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from core.tool_runtime import ToolSet
from core.agent_runtime import configured_budget, global_agent_injections
from core.observability.runtime import global_telemetry
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
        budget = configured_budget("coordinator")
        used_tool_calls = int(state.get("runtime_tool_calls", 0))
        over_budget = used_tool_calls + len(tool_calls) > budget.max_tool_calls
        if over_budget:
            from core.tool_runtime import ToolExecutionError, ToolExecutionResult

            results = [
                ToolExecutionResult(
                    tool_name=call.get("name", ""),
                    ok=False,
                    error=ToolExecutionError(
                        kind="tool_error",
                        message=(
                            "agent tool-call budget exhausted; no further tool execution is allowed"
                        ),
                    ),
                    attempts=0,
                )
                for call in tool_calls
            ]
        else:
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
        persistence_config = {
            **config,
            "configurable": {
                **config.get("configurable", {}),
                "max_tool_result_chars": budget.max_tool_result_chars,
            },
        }
        output = persist_tool_messages(output, persistence_config)
        session_id = str(config.get("configurable", {}).get("thread_id", ""))
        injections_used = int(state.get("runtime_injections", 0))
        follow_ups = await global_agent_injections.drain(
            session_id,
            limit=budget.injection_batch_size,
            remaining_total=max(0, budget.max_injections - injections_used),
        )
        if follow_ups:
            output.extend(follow_ups)
            global_telemetry.event(
                "agent.message.injected",
                payload={
                    "role": "coordinator",
                    "count": len(follow_ups),
                    "total": injections_used + len(follow_ups),
                    "phase": "after_tools",
                },
            )
        global_telemetry.event(
            "agent.tools.completed",
            payload={
                "role": "coordinator",
                "count": len(tool_calls),
                "over_budget": over_budget,
            },
        )
        return {
            "messages": output,
            "runtime_tool_calls": used_tool_calls + len(tool_calls),
            "runtime_injections": injections_used + len(follow_ups),
            "runtime_stop_reason": "tool_budget" if over_budget else None,
        }
