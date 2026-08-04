"""Worker execution seam that makes MySQL leases authoritative."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from gateway.dispatch import TurnTask
from core.rbac import Permission, authorization_service
from server.rbac.service import rbac_service
from server.application.turn_reliability import TurnReliabilityService


@dataclass(frozen=True)
class TurnExecutionContext:
    """Fence values that every side-effecting execution boundary must carry."""

    turn_id: str
    claim_generation: int
    operation_id: str = "turn.execution"


class FencedTurnExecutor:
    """Claim, heartbeat and execute one Turn without exposing lease mechanics."""

    def __init__(
        self,
        unit_of_work_factory: Any,
        reliability: TurnReliabilityService,
        execute: Any,
        *,
        worker_id: str,
        lease_s: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._reliability = reliability
        self._execute = execute
        self._worker_id = worker_id
        self._lease_s = max(3, lease_s)

    async def __call__(self, task: TurnTask) -> bool:
        async with self._unit_of_work_factory.begin() as unit_of_work:
            generation = await self._reliability.claim_turn(
                unit_of_work.session,
                turn_id=task.turn_id,
                worker_id=self._worker_id,
                lease_s=self._lease_s,
            )
            if generation is None:
                return False
            if task.authorization is None:
                raise PermissionError("worker task lacks authorization context")
            principal = await rbac_service.principal_for_user_id(
                unit_of_work.session, task.authorization.submitter_user_id
            )
            if principal.authorization_version != task.authorization.authorization_version:
                raise PermissionError("submitter authorization has changed")
            if task.authorization.workspace_id != task.context.workspace_id:
                raise PermissionError("worker authorization workspace mismatch")
            authorization_service.require(
                principal, Permission.AGENT_TURN_SUBMIT,
                workspace_id=task.authorization.workspace_id,
            )
            await unit_of_work.commit()

        heartbeat = asyncio.create_task(
            self._heartbeat(task.turn_id, generation), name=f"turn-lease:{task.turn_id}"
        )
        try:
            await self._execute(
                task,
                TurnExecutionContext(
                    turn_id=task.turn_id,
                    claim_generation=generation,
                ),
            )
            return True
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, turn_id: str, generation: int) -> None:
        while True:
            await asyncio.sleep(self._lease_s / 3)
            async with self._unit_of_work_factory.begin() as unit_of_work:
                await self._reliability.heartbeat(
                    unit_of_work.session,
                    turn_id=turn_id,
                    generation=generation,
                    worker_id=self._worker_id,
                    lease_s=self._lease_s,
                )
                await unit_of_work.commit()
