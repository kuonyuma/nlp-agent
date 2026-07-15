"""Typed, session-scoped events emitted by isolated Worker agents."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from schemas.models import WorkerUsageSpec


WorkerTerminalStatus = Literal["completed", "failed", "killed"]
SessionNotifier = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WorkerCompletedEvent:
    """A terminal Worker result; this is never a user-authored message."""

    session_id: str
    worker_id: str
    status: WorkerTerminalStatus
    summary: str
    result: str | None
    usage: WorkerUsageSpec | None
    join: bool


class WorkerEventBus:
    """Routes Worker completion events to the owning Coordinator session only."""

    def __init__(self, max_events_per_session: int = 100) -> None:
        self._max_events_per_session = max_events_per_session
        self._queues: dict[str, asyncio.Queue[WorkerCompletedEvent]] = defaultdict(
            lambda: asyncio.Queue(maxsize=self._max_events_per_session)
        )
        self._notifier: SessionNotifier | None = None

    def set_notifier(self, notifier: SessionNotifier | None) -> None:
        self._notifier = notifier

    async def publish(self, event: WorkerCompletedEvent) -> None:
        queue = self._queues[event.session_id]
        await queue.put(event)
        if self._notifier is not None:
            await self._notifier(event.session_id)

    async def get(self, session_id: str) -> WorkerCompletedEvent:
        return await self._queues[session_id].get()

    def drain(self, session_id: str, limit: int = 20) -> list[WorkerCompletedEvent]:
        queue = self._queues[session_id]
        events: list[WorkerCompletedEvent] = []
        while len(events) < limit:
            try:
                events.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def has_pending(self, session_id: str) -> bool:
        return not self._queues[session_id].empty()


global_worker_event_bus = WorkerEventBus()
