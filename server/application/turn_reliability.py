"""MySQL-authoritative outbox, Turn lease fencing and tool-operation idempotency."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.infrastructure.mysql.models import DeadLetterModel, OutboxMessageModel, ToolCallModel, TurnCancellationModel, TurnEventModel, TurnModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LostTurnClaimError(RuntimeError):
    pass


class TurnReliabilityService:
    async def enqueue(self, session: AsyncSession, *, topic: str, payload: dict[str, Any]) -> OutboxMessageModel:
        message = OutboxMessageModel(id=str(uuid.uuid4()), topic=topic, payload_json=payload)
        session.add(message)
        await session.flush()
        return message

    async def claim_turn(self, session: AsyncSession, *, turn_id: str, worker_id: str, lease_s: int) -> int | None:
        turn = await session.scalar(select(TurnModel).where(TurnModel.id == turn_id).with_for_update())
        now = utc_now()
        if turn is None or (turn.status != "accepted" and not (turn.status == "running" and turn.lease_expires_at and turn.lease_expires_at < now)):
            return None
        turn.status = "running"
        turn.claim_generation += 1
        turn.claimed_by = worker_id
        turn.heartbeat_at = now
        turn.lease_expires_at = now + timedelta(seconds=lease_s)
        await session.flush()
        return turn.claim_generation

    async def heartbeat(self, session: AsyncSession, *, turn_id: str, generation: int, worker_id: str, lease_s: int) -> None:
        turn = await session.scalar(select(TurnModel).where(TurnModel.id == turn_id).with_for_update())
        if turn is None or turn.claim_generation != generation or turn.claimed_by != worker_id:
            raise LostTurnClaimError(turn_id)
        now = utc_now()
        turn.heartbeat_at = now
        turn.lease_expires_at = now + timedelta(seconds=lease_s)
        await session.flush()

    async def recover_stuck_turns(self, session: AsyncSession, *, max_retries: int = 3) -> list[str]:
        now = utc_now()
        turns = (await session.scalars(select(TurnModel).where(TurnModel.status == "running", TurnModel.lease_expires_at < now).with_for_update(skip_locked=True))).all()
        recovered: list[str] = []
        for turn in turns:
            if turn.claim_generation >= max_retries * 2:
                turn.status = "failed"
                session.add(DeadLetterModel(id=str(uuid.uuid4()), turn_id=turn.id, outbox_id=None, reason="turn lease recovery limit exceeded", payload_json={"generation": turn.claim_generation}))
                continue
            turn.claim_generation += 1  # recovery invalidates the old owner before a new Worker claim.
            turn.claimed_by = None
            turn.lease_expires_at = None
            session.add(TurnEventModel(id=str(uuid.uuid4()), turn_id=turn.id, sequence=(await self._next_sequence(session, turn.id)), claim_generation=turn.claim_generation, event_type="turn.handover", payload_json={"reason": "lease_expired"}))
            await self.enqueue(session, topic="turn.dispatch", payload={"turn_id": turn.id})
            recovered.append(turn.id)
        await session.flush()
        return recovered

    async def append_event(self, session: AsyncSession, *, turn_id: str, generation: int, event_type: str, payload: dict[str, Any]) -> TurnEventModel:
        turn = await session.scalar(select(TurnModel).where(TurnModel.id == turn_id).with_for_update())
        if turn is None or turn.claim_generation != generation:
            raise LostTurnClaimError(turn_id)
        event = TurnEventModel(id=str(uuid.uuid4()), turn_id=turn_id, sequence=await self._next_sequence(session, turn_id), claim_generation=generation, event_type=event_type, payload_json=payload)
        session.add(event)
        await session.flush()
        return event

    async def record_operation(self, session: AsyncSession, *, turn_id: str, generation: int, operation_id: str, tool_name: str, request: dict[str, Any]) -> ToolCallModel:
        operation = await session.scalar(select(ToolCallModel).where(ToolCallModel.turn_id == turn_id, ToolCallModel.operation_id == operation_id).with_for_update())
        if operation is not None:
            return operation
        operation = ToolCallModel(id=str(uuid.uuid4()), turn_id=turn_id, operation_id=operation_id, claim_generation=generation, tool_name=tool_name, idempotency_key=f"{turn_id}:{operation_id}", request_json=request)
        session.add(operation)
        await session.flush()
        return operation

    async def complete_operation(self, session: AsyncSession, *, turn_id: str, generation: int, operation_id: str, result: dict[str, Any]) -> ToolCallModel:
        turn = await session.scalar(select(TurnModel).where(TurnModel.id == turn_id).with_for_update())
        operation = await session.scalar(select(ToolCallModel).where(ToolCallModel.turn_id == turn_id, ToolCallModel.operation_id == operation_id).with_for_update())
        if turn is None or operation is None or turn.claim_generation != generation or operation.claim_generation != generation:
            raise LostTurnClaimError(turn_id)
        operation.status = "succeeded"
        operation.result_json = result
        await session.flush()
        return operation

    async def _next_sequence(self, session: AsyncSession, turn_id: str) -> int:
        events = (await session.scalars(select(TurnEventModel.sequence).where(TurnEventModel.turn_id == turn_id).order_by(TurnEventModel.sequence.desc()).limit(1))).first()
        return int(events or 0) + 1


class OutboxRelay:
    """Claims outbox rows in MySQL before the at-least-once Redis XADD."""

    def __init__(self, redis: Any, *, stream: str, relay_id: str, lock_s: int = 30) -> None:
        self._redis, self._stream, self._relay_id, self._lock_s = redis, stream, relay_id, lock_s

    async def publish_batch(self, session: AsyncSession, *, limit: int = 100) -> int:
        now = utc_now()
        rows = (await session.scalars(select(OutboxMessageModel).where(OutboxMessageModel.status.in_(("pending", "retry")), OutboxMessageModel.available_at <= now, or_(OutboxMessageModel.locked_until.is_(None), OutboxMessageModel.locked_until < now)).order_by(OutboxMessageModel.available_at, OutboxMessageModel.id).limit(limit).with_for_update(skip_locked=True))).all()
        for row in rows:
            row.status, row.locked_by, row.locked_until, row.attempts = "publishing", self._relay_id, now + timedelta(seconds=self._lock_s), row.attempts + 1
        await session.flush()
        for row in rows:
            redis_id = await self._redis.xadd(self._stream, {"topic": row.topic, "payload": __import__("json").dumps(row.payload_json, ensure_ascii=False)})
            row.status, row.redis_message_id, row.published_at, row.locked_until = "published", str(redis_id), utc_now(), None
        await session.flush()
        return len(rows)
