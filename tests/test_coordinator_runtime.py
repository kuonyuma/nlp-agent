import asyncio
import json

import pytest
from langchain_core.messages import HumanMessage

from core.coordinator_runtime import CoordinatorRuntime
from core.task_manager import global_task_manager
from core.worker_events import WorkerCompletedEvent, WorkerEventBus


@pytest.fixture(autouse=True)
def clear_task_manager():
    active = global_task_manager.active_tasks
    terminal = global_task_manager.terminal_tasks
    global_task_manager.active_tasks = {}
    global_task_manager.terminal_tasks = type(terminal)()
    yield
    for task in global_task_manager.active_tasks.values():
        task.future.cancel()
    global_task_manager.active_tasks = active
    global_task_manager.terminal_tasks = terminal


def register_worker(worker_id, turn_id, *, mode="all", quorum=1, timeout=1.0):
    future = asyncio.create_task(asyncio.sleep(10))
    global_task_manager.register_task(
        worker_id,
        "research",
        "find facts",
        future,
        "session-a",
        join=True,
        parent_turn_id=turn_id,
        wait_mode=mode,
        quorum=quorum,
        wait_timeout_s=timeout,
    )
    return future


def event(worker_id, turn_id, *, event_id=None):
    return WorkerCompletedEvent.create(
        event_id=event_id,
        session_id="session-a",
        worker_id=worker_id,
        parent_turn_id=turn_id,
        attempt=1,
        status="completed",
        summary="done",
        result=f"answer-{worker_id}",
        usage=None,
        join=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "quorum", "completed_workers"),
    [("any", 1, ["w1"]), ("quorum", 2, ["w1", "w2"]), ("all", 1, ["w1", "w2", "w3"])],
)
async def test_wait_barrier_resumes_at_configured_threshold(mode, quorum, completed_workers):
    bus = WorkerEventBus()
    calls = []

    async def invoke(messages, session_id, background, turn_id):
        calls.append((messages, session_id, background, turn_id))

    runtime = CoordinatorRuntime(bus, invoke)
    futures = [register_worker(w, "turn-1", mode=mode, quorum=quorum) for w in ["w1", "w2", "w3"]]
    turn = asyncio.create_task(
        runtime.submit_user_turn("session-a", HumanMessage(content="question", id="turn-1"))
    )
    await asyncio.sleep(0)
    for worker_id in completed_workers:
        global_task_manager.complete_task(worker_id, "completed")
        await bus.publish(event(worker_id, "turn-1"))
    await asyncio.wait_for(turn, 1)

    payload = json.loads(calls[-1][0][0].content.splitlines()[2])
    assert payload["barrier"]["mode"] == mode
    assert payload["barrier"]["timed_out"] is False
    assert len(payload["events"]) == len(completed_workers)
    assert calls[-1][3] == "turn-1"
    for future in futures:
        future.cancel()
    await asyncio.gather(*futures, return_exceptions=True)
    await runtime.close()


@pytest.mark.asyncio
async def test_wait_barrier_reports_timeout_without_worker_result():
    bus = WorkerEventBus()
    calls = []

    async def invoke(messages, session_id, background, turn_id):
        calls.append(messages)

    runtime = CoordinatorRuntime(bus, invoke)
    future = register_worker("slow", "turn-timeout", timeout=0.02)
    await runtime.submit_user_turn(
        "session-a", HumanMessage(content="question", id="turn-timeout")
    )
    payload = json.loads(calls[-1][0].content.splitlines()[2])
    assert payload["barrier"]["timed_out"] is True
    assert payload["events"] == []
    future.cancel()
    await asyncio.gather(future, return_exceptions=True)
    await runtime.close()


@pytest.mark.asyncio
async def test_detached_result_is_serialized_through_runtime():
    bus = WorkerEventBus()
    calls = []

    async def invoke(messages, session_id, background, turn_id):
        calls.append((background, turn_id, messages))

    runtime = CoordinatorRuntime(bus, invoke)
    await runtime.submit_user_turn(
        "session-a", HumanMessage(content="question", id="turn-detached")
    )
    detached = WorkerCompletedEvent.create(
        session_id="session-a",
        worker_id="detached",
        parent_turn_id="turn-detached",
        attempt=1,
        status="completed",
        summary="done",
        result="later",
        usage=None,
        join=False,
    )
    await bus.publish(detached)
    await asyncio.sleep(0.02)
    assert calls[-1][0] is True
    assert calls[-1][1] == "turn-detached"
    await runtime.close()
