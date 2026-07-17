import asyncio

import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from core.agent_runtime import (
    AgentInjectionBus,
    AgentRunBudget,
    AgentRunSnapshot,
    AgentStopReason,
    compact_model_content,
)


def test_runtime_budget_and_snapshot_enforce_independent_limits():
    budget = AgentRunBudget(
        max_iterations=2,
        max_duration_s=10,
        max_tokens=100,
        max_tool_calls=2,
    )
    snapshot = AgentRunSnapshot(iterations=2)
    assert snapshot.limit_reached(budget) == AgentStopReason.MAX_ITERATIONS

    snapshot = AgentRunSnapshot(tokens=100)
    assert snapshot.limit_reached(budget) == AgentStopReason.TOKEN_BUDGET

    snapshot = AgentRunSnapshot(tool_calls=2)
    assert snapshot.limit_reached(budget) == AgentStopReason.TOOL_BUDGET

    with pytest.raises(ValidationError):
        AgentRunBudget(max_iterations=0)


@pytest.mark.asyncio
async def test_injection_bus_preserves_fifo_and_safe_point_limits():
    bus = AgentInjectionBus()
    for index in range(5):
        await bus.publish("s1", HumanMessage(content=f"m{index}"))

    first = await bus.drain("s1", limit=3, remaining_total=4)
    second = await bus.drain("s1", limit=3, remaining_total=1)

    assert [item.content for item in first] == ["m0", "m1", "m2"]
    assert [item.content for item in second] == ["m3"]
    assert bus.pending("s1") == 1
    await bus.clear("s1")
    assert bus.pending("s1") == 0


def test_tool_content_compaction_keeps_head_tail_and_hard_limit():
    content = "a" * 2000 + "TAIL"
    compacted = compact_model_content(content, 512)

    assert len(compacted) <= 512
    assert compacted.startswith("a")
    assert compacted.endswith("TAIL")
    assert "tool result compacted" in compacted
