from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.learning import TeachingMaterials
from core.session_context import SessionContext
from gateway.dispatch import TurnTask


@pytest.mark.asyncio
async def test_fenced_executor_claims_turn_before_invoking_agent() -> None:
    from server.worker.fencing import FencedTurnExecutor

    session = AsyncMock()
    unit_of_work = AsyncMock()
    unit_of_work.session = session
    unit_of_work.__aenter__.return_value = unit_of_work
    factory = MagicMock()
    factory.begin.return_value = unit_of_work
    reliability = AsyncMock()
    reliability.claim_turn.return_value = 4
    execute = AsyncMock()
    task = TurnTask(
        context=SessionContext(session_id="session-1"),
        turn_id="turn-1",
        content="hello",
        learning_context=None,
        learning_progress=None,
        exercise_state=None,
        teaching_materials=TeachingMaterials(),
        guided_session_id=None,
        exercise_session_id=None,
    )

    claimed = await FencedTurnExecutor(factory, reliability, execute, worker_id="worker-a", lease_s=30)(task)

    assert claimed is True
    reliability.claim_turn.assert_awaited_once_with(
        session, turn_id="turn-1", worker_id="worker-a", lease_s=30
    )
    unit_of_work.commit.assert_awaited_once()
    execute.assert_awaited_once()
    execution = execute.await_args.args[1]
    assert execution.turn_id == "turn-1"
    assert execution.claim_generation == 4
    assert execution.operation_id == "turn.execution"


@pytest.mark.asyncio
async def test_fenced_executor_does_not_execute_turn_lost_to_another_worker() -> None:
    from server.worker.fencing import FencedTurnExecutor

    unit_of_work = AsyncMock()
    unit_of_work.session = AsyncMock()
    unit_of_work.__aenter__.return_value = unit_of_work
    factory = MagicMock()
    factory.begin.return_value = unit_of_work
    reliability = AsyncMock()
    reliability.claim_turn.return_value = None
    execute = AsyncMock()
    task = TurnTask(
        context=SessionContext(session_id="session-1"), turn_id="turn-1", content="hello",
        learning_context=None, learning_progress=None, exercise_state=None,
        teaching_materials=TeachingMaterials(), guided_session_id=None, exercise_session_id=None,
    )

    claimed = await FencedTurnExecutor(factory, reliability, execute, worker_id="worker-a", lease_s=30)(task)

    assert claimed is False
    execute.assert_not_awaited()
