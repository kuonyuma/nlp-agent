import asyncio

import pytest
from langchain_core.messages import HumanMessage

from core.coordinator_runtime import CoordinatorRuntime
from core.task_manager import global_task_manager
from core.worker_events import WorkerCompletedEvent, WorkerEventBus


@pytest.fixture(autouse=True)
def clear_task_manager():
    original = global_task_manager.active_tasks
    global_task_manager.active_tasks = {}
    yield
    global_task_manager.active_tasks = original


@pytest.mark.asyncio
async def test_joined_worker_result_resumes_the_same_serialized_session():
    bus = WorkerEventBus()
    calls = []

    async def invoke(messages, session_id, background):
        calls.append((messages, session_id, background))

    runtime = CoordinatorRuntime(bus, invoke, aggregation_delay_s=0)
    worker_future = asyncio.create_task(asyncio.sleep(10))
    global_task_manager.register_task(
        "worker-1", "research", "find facts", worker_future, "session-a", join=True
    )
    turn = asyncio.create_task(
        runtime.submit_user_turn("session-a", HumanMessage(content="question"))
    )
    await asyncio.sleep(0)
    global_task_manager.complete_task("worker-1", "completed")
    await bus.publish(
        WorkerCompletedEvent(
            session_id="session-a",
            worker_id="worker-1",
            status="completed",
            summary="done",
            result="answer",
            usage=None,
            join=True,
        )
    )
    await turn
    worker_future.cancel()
    await asyncio.gather(worker_future, return_exceptions=True)

    assert len(calls) == 2
    assert calls[0][2] is False
    assert calls[1][2] is False
    assert "INTERNAL_WORKER_RESULTS" in calls[1][0][0].content
    await runtime.close()


@pytest.mark.asyncio
async def test_detached_worker_result_is_delivered_by_the_runtime_not_worker():
    bus = WorkerEventBus()
    calls = []

    async def invoke(messages, session_id, background):
        calls.append((messages, session_id, background))

    runtime = CoordinatorRuntime(bus, invoke, aggregation_delay_s=0)
    await runtime.submit_user_turn("session-b", HumanMessage(content="question"))
    await bus.publish(
        WorkerCompletedEvent(
            session_id="session-b",
            worker_id="worker-2",
            status="completed",
            summary="done",
            result="later",
            usage=None,
            join=False,
        )
    )
    await asyncio.sleep(0.02)

    assert len(calls) == 2
    assert calls[1][2] is True
    await runtime.close()
