"""Transactional task dispatch seam for MySQL-authoritative Turn delivery."""

from __future__ import annotations

from typing import Any

from gateway.dispatch import TurnTask
from gateway.redis_transport import TurnTaskCodec
from server.application.turn_reliability import TurnReliabilityService


class OutboxTurnDispatcher:
    """Persist a Turn task in MySQL; the relay is the only Redis publisher."""

    def __init__(
        self,
        unit_of_work_factory: Any,
        reliability: TurnReliabilityService,
        transport: Any,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._reliability = reliability
        self._transport = transport
        self._active: set[str] = set()

    async def submit(self, task: TurnTask) -> None:
        async with self._unit_of_work_factory.begin() as unit_of_work:
            await self._reliability.enqueue(
                unit_of_work.session,
                topic="turn.dispatch",
                payload={"task": TurnTaskCodec.dumps(task)},
            )
            await unit_of_work.commit()
        self._active.add(task.turn_id)

    async def cancel(self, turn_id: str) -> None:
        await self._transport.cancel(turn_id)
        self._active.discard(turn_id)

    async def inject(self, turn_id: str, content: str) -> None:
        await self._transport.inject(turn_id, content)

    async def close(self, *, force: bool = False, grace_s: float = 0) -> None:
        await self._transport.close(force=force, grace_s=grace_s)
        self._active.clear()

    def active_count(self) -> int:
        return len(self._active)
