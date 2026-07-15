import asyncio

import pytest

from core.task_manager import TaskManager
from core.worker_protocol import WorkerCommand


@pytest.mark.asyncio
async def test_typed_worker_command_and_mailbox_backpressure():
    manager = TaskManager(mailbox_size=1)
    future = asyncio.create_task(asyncio.sleep(10))
    manager.register_task("w1", "research", "task", future, "s1")
    first = WorkerCommand.create(
        session_id="s1", worker_id="w1", kind="continue", content="more"
    )
    second = WorkerCommand.create(
        session_id="s1", worker_id="w1", kind="reprioritize", content="urgent"
    )

    assert manager.queue_command(first) is True
    assert manager.queue_command(second) is False
    assert manager.get_active_task("w1").pending_messages.get_nowait() == first
    assert manager.metrics_snapshot()["commands_rejected"] == 1
    future.cancel()
    await asyncio.gather(future, return_exceptions=True)


@pytest.mark.asyncio
async def test_terminal_tasks_leave_active_set_and_are_pruned():
    manager = TaskManager(terminal_limit=1)
    futures = []
    for worker_id in ["w1", "w2"]:
        future = asyncio.create_task(asyncio.sleep(10))
        futures.append(future)
        manager.register_task(worker_id, "research", "task", future, "s1")
        manager.complete_task(worker_id, "completed")

    assert manager.active_tasks == {}
    assert list(manager.terminal_tasks) == ["w2"]
    assert manager.metrics_snapshot()["terminal_tasks_pruned"] == 1
    for future in futures:
        future.cancel()
    await asyncio.gather(*futures, return_exceptions=True)
