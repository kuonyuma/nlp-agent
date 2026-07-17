"""Worker lifecycle, capacity, cancellation, retention, and wait management."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from core.worker_lifecycle import (
    TERMINAL_STATUSES,
    WorkerLifecycleStatus,
    WorkerResourceBudget,
    WorkerRetryPolicy,
    WorkerTerminalStatus,
    validate_transition,
)
from core.worker_protocol import WorkerCommand, WorkerWaitMode, WorkerWaitPlan
from schemas.models import WorkerExecutionResultSpec
from utils.logger import get_logger


logger = get_logger("nlp_agent.task_manager")


@dataclass(slots=True)
class TaskManagerMetrics:
    commands_enqueued: int = 0
    commands_rejected: int = 0
    terminal_tasks_pruned: int = 0
    lifecycle_transitions: int = 0
    cancellations_requested: int = 0
    capacity_waits: int = 0


@dataclass(frozen=True, slots=True)
class WorkerTraceEvent:
    sequence: int
    timestamp: float
    status: WorkerLifecycleStatus
    reason: str
    attempt: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActiveTaskInfo:
    task_id: str
    task_type: str
    command: str
    future: asyncio.Task
    session_id: str
    join: bool
    parent_turn_id: str = ""
    parent_worker_id: str = ""
    wait_mode: WorkerWaitMode = "all"
    quorum: int = 1
    wait_timeout_s: float = 60.0
    attempt: int = 1
    status: WorkerLifecycleStatus = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    wait_consumed: bool = False
    capacity_acquired: bool = False
    cancellation_reason: str = ""
    result: WorkerExecutionResultSpec | None = None
    budget: WorkerResourceBudget = field(default_factory=WorkerResourceBudget)
    retry_policy: WorkerRetryPolicy = field(default_factory=WorkerRetryPolicy)
    pending_messages: asyncio.Queue[WorkerCommand] = field(default_factory=asyncio.Queue)
    trace: list[WorkerTraceEvent] = field(default_factory=list)


class TaskManager:
    def __init__(
        self,
        *,
        mailbox_size: int = 20,
        terminal_limit: int = 100,
        terminal_ttl_s: float = 3600.0,
        max_concurrent_workers: int = 8,
        max_concurrent_per_session: int = 4,
        trace_limit: int = 200,
    ) -> None:
        if max_concurrent_workers < 1 or max_concurrent_per_session < 1:
            raise ValueError("Worker concurrency limits must be positive")
        self.mailbox_size = mailbox_size
        self.terminal_limit = terminal_limit
        self.terminal_ttl_s = terminal_ttl_s
        self.max_concurrent_workers = max_concurrent_workers
        self.max_concurrent_per_session = max_concurrent_per_session
        self.trace_limit = trace_limit
        self.active_tasks: dict[str, ActiveTaskInfo] = {}
        self.terminal_tasks: OrderedDict[str, ActiveTaskInfo] = OrderedDict()
        self.metrics = TaskManagerMetrics()
        self._running_total = 0
        self._running_by_session: dict[str, int] = defaultdict(int)
        self._capacity_waiters: list[asyncio.Future[None]] = []

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
        parent_worker_id: str = "",
        wait_mode: WorkerWaitMode = "all",
        quorum: int = 1,
        wait_timeout_s: float = 60.0,
        budget: WorkerResourceBudget | None = None,
        retry_policy: WorkerRetryPolicy | None = None,
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
            parent_worker_id=parent_worker_id,
            wait_mode=wait_mode,
            quorum=max(1, quorum),
            wait_timeout_s=max(0.1, wait_timeout_s),
            attempt=attempt,
            budget=budget or WorkerResourceBudget(),
            retry_policy=retry_policy or WorkerRetryPolicy(),
            pending_messages=asyncio.Queue(maxsize=self.mailbox_size),
        )
        self.active_tasks[task_id] = task
        self._append_trace(task, "registered")
        logger.debug("Worker registered", task_id=task_id, attempt=attempt)
        return task

    def get_task(self, task_id: str) -> Optional[ActiveTaskInfo]:
        self.cleanup_terminal()
        return self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)

    def get_active_task(self, task_id: str) -> Optional[ActiveTaskInfo]:
        return self.active_tasks.get(task_id)

    def queue_command(self, command: WorkerCommand) -> bool:
        task = self.active_tasks.get(command.worker_id)
        if task is None or task.session_id != command.session_id or task.status in TERMINAL_STATUSES:
            self.metrics.commands_rejected += 1
            return False
        try:
            task.pending_messages.put_nowait(command)
        except asyncio.QueueFull:
            self.metrics.commands_rejected += 1
            logger.warning("Worker mailbox is full", task_id=command.worker_id)
            return False
        self.metrics.commands_enqueued += 1
        self._append_trace(task, "command_enqueued", command_id=command.command_id, kind=command.kind)
        return True

    def transition_task(
        self,
        task_id: str,
        status: WorkerLifecycleStatus,
        reason: str,
        **metadata: Any,
    ) -> ActiveTaskInfo:
        task = self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        validate_transition(task.status, status)
        task.status = status
        now = time.time()
        if status == "running" and task.started_at is None:
            task.started_at = now
        if status in TERMINAL_STATUSES:
            task.completed_at = now
        self.metrics.lifecycle_transitions += 1
        self._append_trace(task, reason, **metadata)
        logger.debug("Worker transitioned", task_id=task_id, status=status, reason=reason)
        return task

    def set_attempt(self, task_id: str, attempt: int) -> None:
        task = self.active_tasks.get(task_id)
        if task is None:
            return
        task.attempt = attempt
        self._append_trace(task, "attempt_started", attempt=attempt)

    def complete_task(
        self,
        task_id: str,
        status: WorkerTerminalStatus,
        result: WorkerExecutionResultSpec | None = None,
    ) -> None:
        task = self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)
        if task is None:
            return
        if task.status not in TERMINAL_STATUSES:
            self.transition_task(task_id, status, result.termination_reason if result else status)
        task.result = result or task.result
        self.active_tasks.pop(task_id, None)
        self.terminal_tasks[task_id] = task
        self.terminal_tasks.move_to_end(task_id)
        self.cleanup_terminal()

    async def acquire_execution_slot(self, task_id: str) -> None:
        while True:
            task = self.active_tasks.get(task_id)
            if task is None:
                raise asyncio.CancelledError
            session_count = self._running_by_session[task.session_id]
            if (
                self._running_total < self.max_concurrent_workers
                and session_count < self.max_concurrent_per_session
            ):
                self._running_total += 1
                self._running_by_session[task.session_id] += 1
                task.capacity_acquired = True
                self.transition_task(task_id, "running", "capacity_acquired")
                return

            waiter = asyncio.get_running_loop().create_future()
            self._capacity_waiters.append(waiter)
            self.metrics.capacity_waits += 1
            self._append_trace(task, "capacity_wait")
            try:
                await waiter
            finally:
                if waiter in self._capacity_waiters:
                    self._capacity_waiters.remove(waiter)

    def release_execution_slot(self, task_id: str) -> None:
        task = self.active_tasks.get(task_id) or self.terminal_tasks.get(task_id)
        if task is None or not task.capacity_acquired:
            return
        task.capacity_acquired = False
        self._running_total = max(0, self._running_total - 1)
        self._running_by_session[task.session_id] = max(
            0, self._running_by_session[task.session_id] - 1
        )
        self._append_trace(task, "capacity_released")
        for waiter in list(self._capacity_waiters):
            if not waiter.done():
                waiter.set_result(None)

    def stop_task(self, task_id: str, reason: str = "coordinator_cancelled") -> dict[str, str]:
        task = self.active_tasks.get(task_id)
        if task is None:
            raise ValueError(f"No active task found with ID: {task_id}")
        if task.status != "cancelling":
            self.transition_task(task_id, "cancelling", reason)
        task.cancellation_reason = reason
        self.metrics.cancellations_requested += 1
        self.cancel_descendants(task_id, reason=f"parent_cancelled:{task_id}")
        task.future.cancel()
        return {"taskId": task.task_id, "taskType": task.task_type, "command": task.command}

    def cancel_workers(self, worker_ids: set[str] | frozenset[str], reason: str) -> list[str]:
        cancelled: list[str] = []
        for worker_id in worker_ids:
            if worker_id not in self.active_tasks:
                continue
            self.stop_task(worker_id, reason=reason)
            cancelled.append(worker_id)
        return cancelled

    def cancel_descendants(self, parent_worker_id: str, reason: str) -> list[str]:
        direct_children = [
            task.task_id
            for task in self.active_tasks.values()
            if task.parent_worker_id == parent_worker_id
        ]
        cancelled: list[str] = []
        for child_id in direct_children:
            if child_id in self.active_tasks:
                self.stop_task(child_id, reason=reason)
                cancelled.append(child_id)
        return cancelled

    def cancel_session(self, session_id: str, reason: str = "session_cancelled") -> list[str]:
        worker_ids = {
            task.task_id for task in self.active_tasks.values() if task.session_id == session_id
        }
        return self.cancel_workers(worker_ids, reason)

    def cancel_turn(
        self, session_id: str, parent_turn_id: str, reason: str = "turn_cancelled"
    ) -> list[str]:
        worker_ids = {
            task.task_id
            for task in self.active_tasks.values()
            if task.session_id == session_id and task.parent_turn_id == parent_turn_id
        }
        return self.cancel_workers(worker_ids, reason)

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

    def task_snapshot(self, task_id: str) -> dict[str, Any] | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "session_id": task.session_id,
            "parent_turn_id": task.parent_turn_id,
            "parent_worker_id": task.parent_worker_id,
            "status": task.status,
            "attempt": task.attempt,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "cancellation_reason": task.cancellation_reason or None,
            "result": task.result.model_dump() if task.result else None,
        }

    def task_timeline(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if task is None:
            return []
        return [
            {
                "sequence": event.sequence,
                "timestamp": event.timestamp,
                "status": event.status,
                "reason": event.reason,
                "attempt": event.attempt,
                "metadata": event.metadata,
            }
            for event in task.trace
        ]

    def cleanup_terminal(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
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
            "running_workers": self._running_total,
            "commands_enqueued": self.metrics.commands_enqueued,
            "commands_rejected": self.metrics.commands_rejected,
            "terminal_tasks_pruned": self.metrics.terminal_tasks_pruned,
            "lifecycle_transitions": self.metrics.lifecycle_transitions,
            "cancellations_requested": self.metrics.cancellations_requested,
            "capacity_waits": self.metrics.capacity_waits,
        }

    def _append_trace(self, task: ActiveTaskInfo, reason: str, **metadata: Any) -> None:
        task.trace.append(
            WorkerTraceEvent(
                sequence=(task.trace[-1].sequence + 1) if task.trace else 1,
                timestamp=time.time(),
                status=task.status,
                reason=reason,
                attempt=task.attempt,
                metadata=metadata,
            )
        )
        if len(task.trace) > self.trace_limit:
            del task.trace[: len(task.trace) - self.trace_limit]


global_task_manager = TaskManager()
