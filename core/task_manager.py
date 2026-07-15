"""Lifecycle, mailbox, retention, and wait-policy management for Workers."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from core.worker_protocol import WorkerCommand, WorkerWaitMode, WorkerWaitPlan
from utils.logger import get_logger


logger = get_logger("nlp_agent.task_manager")


@dataclass(slots=True)
class TaskManagerMetrics:
    commands_enqueued: int = 0
    commands_rejected: int = 0
    terminal_tasks_pruned: int = 0


@dataclass(slots=True)
class ActiveTaskInfo:
    task_id: str
    task_type: str
    command: str
    future: asyncio.Task
    session_id: str
    join: bool
    parent_turn_id: str = ""
    wait_mode: WorkerWaitMode = "all"
    quorum: int = 1
    wait_timeout_s: float = 60.0
    attempt: int = 1
    status: str = "running"
    completed_at: float | None = None
    wait_consumed: bool = False
    pending_messages: asyncio.Queue[WorkerCommand] = field(default_factory=asyncio.Queue)


class TaskManager:
    def __init__(
        self,
        *,
        mailbox_size: int = 20,
        terminal_limit: int = 100,
        terminal_ttl_s: float = 3600.0,
    ) -> None:
        self.mailbox_size = mailbox_size
        self.terminal_limit = terminal_limit
        self.terminal_ttl_s = terminal_ttl_s
        self.active_tasks: dict[str, ActiveTaskInfo] = {}
        self.terminal_tasks: OrderedDict[str, ActiveTaskInfo] = OrderedDict()
        self.metrics = TaskManagerMetrics()

    def register_task(
        self,
        task_id: str,
        task_type: str,
        command: str,
        future: asyncio.Task,
        session_id: str,
        join: bool = True,
        *,
        parent_turn_id: str = "",
        wait_mode: WorkerWaitMode = "all",
        quorum: int = 1,
        wait_timeout_s: float = 60.0,
    ) -> ActiveTaskInfo:
        previous = self.active_tasks.pop(task_id, None) or self.terminal_tasks.pop(task_id, None)
        attempt = previous.attempt + 1 if previous else 1
        task = ActiveTaskInfo(
            task_id=task_id,
            task_type=task_type,
            command=command,
            future=future,
            session_id=session_id,
            join=join,
            parent_turn_id=parent_turn_id,
            wait_mode=wait_mode,
            quorum=max(1, quorum),
            wait_timeout_s=max(0.1, wait_timeout_s),
            attempt=attempt,
            pending_messages=asyncio.Queue(maxsize=self.mailbox_size),
        )
        self.active_tasks[task_id] = task
        logger.debug("Worker registered", task_id=task_id, attempt=attempt)
        return task

    def get_task(self, task_id: str) -> Optional[ActiveTaskInfo]:
        self.cleanup_terminal()
        return self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)

    def get_active_task(self, task_id: str) -> Optional[ActiveTaskInfo]:
        return self.active_tasks.get(task_id)

    def queue_command(self, command: WorkerCommand) -> bool:
        task = self.active_tasks.get(command.worker_id)
        if task is None or task.session_id != command.session_id:
            self.metrics.commands_rejected += 1
            return False
        try:
            task.pending_messages.put_nowait(command)
        except asyncio.QueueFull:
            self.metrics.commands_rejected += 1
            logger.warning("Worker mailbox is full", task_id=command.worker_id)
            return False
        self.metrics.commands_enqueued += 1
        return True

    def complete_task(self, task_id: str, status: str) -> None:
        task = self.active_tasks.pop(task_id, None)
        if task is None:
            task = self.terminal_tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.completed_at = time.monotonic()
        self.terminal_tasks[task_id] = task
        self.terminal_tasks.move_to_end(task_id)
        self.cleanup_terminal()

    def stop_task(self, task_id: str) -> dict:
        task = self.active_tasks.get(task_id)
        if task is None:
            raise ValueError(f"No running task found with ID: {task_id}")
        task.future.cancel()
        self.complete_task(task_id, "killed")
        return {"taskId": task.task_id, "taskType": task.task_type, "command": task.command}

    def build_wait_plan(self, session_id: str, parent_turn_id: str) -> WorkerWaitPlan | None:
        tasks = [
            task
            for task in [*self.active_tasks.values(), *self.terminal_tasks.values()]
            if task.session_id == session_id
            and task.parent_turn_id == parent_turn_id
            and task.join
            and not task.wait_consumed
        ]
        if not tasks:
            return None
        modes = {task.wait_mode for task in tasks}
        mode: WorkerWaitMode = modes.pop() if len(modes) == 1 else "all"
        quorum = min(len(tasks), max(task.quorum for task in tasks))
        timeout_s = min(task.wait_timeout_s for task in tasks)
        return WorkerWaitPlan(
            session_id=session_id,
            parent_turn_id=parent_turn_id,
            worker_ids=frozenset(task.task_id for task in tasks),
            mode=mode,
            quorum=quorum,
            timeout_s=timeout_s,
        )

    def mark_wait_consumed(self, worker_ids: frozenset[str]) -> None:
        for task_id in worker_ids:
            task = self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)
            if task:
                task.wait_consumed = True

    def cleanup_terminal(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        removed = 0
        for task_id, task in list(self.terminal_tasks.items()):
            expired = task.completed_at is not None and now - task.completed_at > self.terminal_ttl_s
            over_limit = len(self.terminal_tasks) - removed > self.terminal_limit
            if not expired and not over_limit:
                continue
            self.terminal_tasks.pop(task_id, None)
            removed += 1
        self.metrics.terminal_tasks_pruned += removed
        return removed

    def metrics_snapshot(self) -> dict[str, int]:
        return {
            "active_tasks": len(self.active_tasks),
            "terminal_tasks": len(self.terminal_tasks),
            "commands_enqueued": self.metrics.commands_enqueued,
            "commands_rejected": self.metrics.commands_rejected,
            "terminal_tasks_pruned": self.metrics.terminal_tasks_pruned,
        }


global_task_manager = TaskManager()
