import pytest
from langgraph.graph import END
from langchain_core.messages import AIMessage

from core.tool_runtime import ToolExecutionResult
from server.agent.grapy import _route_after_tools
from server.tools.runtime_tool_node import RuntimeToolNode


class FakeToolSet:
    def __init__(self, results: list[ToolExecutionResult]) -> None:
        self._results = results

    async def execute_many(self, _calls, _config):
        return self._results


def test_graph_ends_turn_when_joined_worker_barrier_is_armed():
    assert _route_after_tools({"runtime_wait_for_workers": True}) == END
    assert _route_after_tools({"runtime_wait_for_workers": False}) == "coordinator"


@pytest.mark.asyncio
async def test_joined_worker_dispatch_forces_graph_barrier(monkeypatch):
    monkeypatch.setattr(
        "server.tools.runtime_tool_node.persist_tool_messages", lambda messages, _config: messages
    )
    node = RuntimeToolNode(
        lambda _config: FakeToolSet([
            ToolExecutionResult(
                tool_name="spawn_worker",
                ok=True,
                output='{"task_id":"worker-1","status":"started","join":true}',
            )
        ])
    )

    result = await node(
        {"messages": [AIMessage(content="", tool_calls=[{
            "name": "spawn_worker", "args": {"agent_name": "nlp_calculator"}, "id": "call-1"
        }])], "runtime_tool_calls": 0, "runtime_injections": 0},
        {"configurable": {"thread_id": "session-a"}},
    )

    assert result["runtime_wait_for_workers"] is True


@pytest.mark.asyncio
async def test_detached_worker_dispatch_does_not_force_graph_barrier(monkeypatch):
    monkeypatch.setattr(
        "server.tools.runtime_tool_node.persist_tool_messages", lambda messages, _config: messages
    )
    node = RuntimeToolNode(
        lambda _config: FakeToolSet([
            ToolExecutionResult(
                tool_name="spawn_worker",
                ok=True,
                output='{"task_id":"worker-1","status":"started","join":false}',
            )
        ])
    )

    result = await node(
        {"messages": [AIMessage(content="", tool_calls=[{
            "name": "spawn_worker", "args": {"agent_name": "nlp_calculator", "join": False}, "id": "call-1"
        }])], "runtime_tool_calls": 0, "runtime_injections": 0},
        {"configurable": {"thread_id": "session-a"}},
    )

    assert result["runtime_wait_for_workers"] is False
