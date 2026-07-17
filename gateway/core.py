"""Lifecycle-owning Backend Gateway Core; HTTP frameworks adapt to this class."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.session_context import SessionContext
from gateway.contracts import (
    GatewayEvent,
    GatewayEventType,
    GatewayHealth,
    GatewayNotStartedError,
    InjectMessageRequest,
    ResourceNotFoundError,
    SubmitTurnRequest,
    TurnAccepted,
    TurnConflictError,
    TurnRecord,
    TurnStatus,
)
from gateway.engine import AgentEngine, LangGraphAgentEngine
from gateway.events import GatewayEventBroker
from gateway.repository import GatewayRepository
from server.agent.session_service import LocalSessionService, local_session_service


class BackendGateway:
    """The single writer and lifecycle owner for all backend Agent traffic."""

    def __init__(
        self,
        *,
        engine: AgentEngine | None = None,
        repository: GatewayRepository | None = None,
        sessions: LocalSessionService = local_session_service,
    ) -> None:
        project = Path(__file__).resolve().parent.parent
        from configs.settings import settings

        gateway_config = settings.gateway_runtime
        database = Path(gateway_config.get("database", ".data/gateway/gateway.sqlite3"))
        if not database.is_absolute():
            database = project / database
        self.engine = engine or LangGraphAgentEngine()
        self.repository = repository or GatewayRepository(
            database
        )
        self.sessions = sessions
        self.events = GatewayEventBroker()
        self._turn_tasks: dict[str, asyncio.Task[None]] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._started = False
        self._accepting = False

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            await self.engine.start(self._emit_from_engine)
            interrupted = await asyncio.to_thread(self.repository.recover_interrupted)
            for turn in interrupted:
                await self._emit(
                    turn.turn_id,
                    turn.session_id,
                    GatewayEventType.TURN_FAILED,
                    {"status": "interrupted", "error_kind": "gateway_restart"},
                )
            for event in await asyncio.to_thread(self.repository.pending_outbox):
                self.events.publish(event)
                await asyncio.to_thread(self.repository.mark_delivered, event.event_id)
            self._started = True
            self._accepting = True

    def _require_started(self) -> None:
        if not self._started or not self._accepting:
            raise GatewayNotStartedError("Backend Gateway is not accepting turns")

    async def create_session(
        self,
        principal: AuthenticatedPrincipal,
        *,
        workspace_id: str = "default",
        channel: str = "web",
    ) -> SessionContext:
        self._require_started()
        return await self.sessions.create(
            principal, workspace_id=workspace_id, channel=channel
        )

    async def submit_turn(
        self, principal: AuthenticatedPrincipal, request: SubmitTurnRequest
    ) -> TurnAccepted:
        self._require_started()
        context = await self.sessions.resolve(principal, request.session_id)
        await self.sessions.touch(principal, request.session_id)
        turn_id = str(uuid.uuid4())
        turn, duplicate = await asyncio.to_thread(
            self.repository.create_turn,
            turn_id=turn_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            input_text=request.content,
            idempotency_key=request.idempotency_key,
        )
        if duplicate:
            return TurnAccepted(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                status=turn.status,
                duplicate=True,
            )
        active = await asyncio.to_thread(
            self.repository.active_turn_for_session,
            context.session_id,
            exclude_turn_id=turn.turn_id,
        )
        if active is not None:
            await asyncio.to_thread(
                self.repository.update_turn,
                turn.turn_id,
                TurnStatus.FAILED,
                error_kind="turn_conflict",
                error_message=f"session already has active turn {active.turn_id}",
            )
            raise TurnConflictError(active.turn_id)
        await self._emit(
            turn.turn_id,
            context.session_id,
            GatewayEventType.TURN_ACCEPTED,
            {"status": TurnStatus.ACCEPTED.value},
        )
        task = asyncio.create_task(
            self._run_turn(context, turn.turn_id, request.content),
            name=f"gateway-turn:{turn.turn_id}",
        )
        self._turn_tasks[turn.turn_id] = task
        task.add_done_callback(lambda _task, tid=turn.turn_id: self._turn_tasks.pop(tid, None))
        return TurnAccepted(
            turn_id=turn.turn_id,
            session_id=context.session_id,
            status=TurnStatus.ACCEPTED,
        )

    async def _run_turn(
        self, context: SessionContext, turn_id: str, content: str
    ) -> None:
        await asyncio.to_thread(
            self.repository.update_turn, turn_id, TurnStatus.RUNNING
        )
        await self._emit(
            turn_id,
            context.session_id,
            GatewayEventType.TURN_STARTED,
            {"status": TurnStatus.RUNNING.value},
        )
        try:
            final_text = await self.engine.run_turn(context, turn_id, content)
        except asyncio.CancelledError:
            await self.engine.cancel_turn(context, turn_id)
            await asyncio.to_thread(
                self.repository.update_turn, turn_id, TurnStatus.CANCELLED
            )
            await self._emit(
                turn_id,
                context.session_id,
                GatewayEventType.TURN_CANCELLED,
                {"status": TurnStatus.CANCELLED.value},
            )
            raise
        except Exception as error:
            await asyncio.to_thread(
                self.repository.update_turn,
                turn_id,
                TurnStatus.FAILED,
                error_kind=type(error).__name__,
                error_message=str(error),
            )
            await self._emit(
                turn_id,
                context.session_id,
                GatewayEventType.TURN_FAILED,
                {
                    "status": TurnStatus.FAILED.value,
                    "error_kind": type(error).__name__,
                    "message": str(error)[:500],
                },
            )
            return
        await asyncio.to_thread(
            self.repository.update_turn,
            turn_id,
            TurnStatus.COMPLETED,
            final_text=final_text,
        )
        await self._emit(
            turn_id,
            context.session_id,
            GatewayEventType.MESSAGE_COMPLETED,
            {"content": final_text},
        )
        await self._emit(
            turn_id,
            context.session_id,
            GatewayEventType.TURN_COMPLETED,
            {"status": TurnStatus.COMPLETED.value},
        )

    async def inject_message(
        self, principal: AuthenticatedPrincipal, request: InjectMessageRequest
    ) -> TurnAccepted:
        self._require_started()
        context = await self.sessions.resolve(principal, request.session_id)
        turn_id = await self.engine.inject(context, request.content)
        if turn_id is None:
            raise TurnConflictError("session has no active turn")
        await self._emit(
            turn_id,
            context.session_id,
            GatewayEventType.MESSAGE_INJECTED,
            {"content": request.content},
        )
        turn = await asyncio.to_thread(self.repository.get_turn, turn_id)
        return TurnAccepted(
            turn_id=turn_id,
            session_id=context.session_id,
            status=turn.status if turn else TurnStatus.RUNNING,
        )

    async def cancel_turn(
        self, principal: AuthenticatedPrincipal, turn_id: str
    ) -> TurnRecord:
        turn = await self.get_turn(principal, turn_id)
        if turn.status not in {TurnStatus.ACCEPTED, TurnStatus.RUNNING}:
            return turn
        context = await self.sessions.resolve(principal, turn.session_id)
        await self.engine.cancel_turn(context, turn_id)
        task = self._turn_tasks.get(turn_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        updated = await asyncio.to_thread(self.repository.get_turn, turn_id)
        return updated or turn

    async def get_turn(
        self, principal: AuthenticatedPrincipal, turn_id: str
    ) -> TurnRecord:
        turn = await asyncio.to_thread(self.repository.get_turn, turn_id)
        if turn is None:
            raise ResourceNotFoundError(turn_id)
        if not principal.is_admin and (
            turn.user_id != principal.user_id
            or (
                "*" not in principal.workspace_ids
                and turn.workspace_id not in principal.workspace_ids
            )
        ):
            raise AccessDeniedError(turn_id)
        return turn

    async def replay_events(
        self,
        principal: AuthenticatedPrincipal,
        turn_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[GatewayEvent]:
        await self.get_turn(principal, turn_id)
        return await asyncio.to_thread(
            self.repository.events_after,
            turn_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def stream_events(
        self,
        principal: AuthenticatedPrincipal,
        turn_id: str,
        *,
        after_sequence: int = 0,
        max_queue: int = 500,
    ) -> AsyncIterator[GatewayEvent]:
        turn = await self.get_turn(principal, turn_id)
        subscription_id, queue = self.events.subscribe(
            turn_id=turn_id, maxsize=max_queue
        )
        last_sequence = max(0, after_sequence)
        try:
            history = await self.replay_events(
                principal, turn_id, after_sequence=last_sequence, limit=2000
            )
            for event in history:
                last_sequence = event.sequence
                yield event
            if turn.status in {
                TurnStatus.COMPLETED,
                TurnStatus.FAILED,
                TurnStatus.CANCELLED,
                TurnStatus.INTERRUPTED,
            }:
                return
            while True:
                event = await queue.get()
                if event.sequence <= last_sequence:
                    continue
                if event.sequence > last_sequence + 1:
                    missing = await self.replay_events(
                        principal,
                        turn_id,
                        after_sequence=last_sequence,
                        limit=event.sequence - last_sequence,
                    )
                    for replayed in missing:
                        last_sequence = replayed.sequence
                        yield replayed
                    if event.sequence <= last_sequence:
                        continue
                last_sequence = event.sequence
                yield event
                if event.type in {
                    GatewayEventType.TURN_COMPLETED,
                    GatewayEventType.TURN_FAILED,
                    GatewayEventType.TURN_CANCELLED,
                }:
                    return
        finally:
            self.events.unsubscribe(subscription_id)

    async def delete_session(
        self, principal: AuthenticatedPrincipal, session_id: str
    ) -> None:
        context = await self.sessions.resolve(principal, session_id)
        active = await asyncio.to_thread(
            self.repository.active_turn_for_session, session_id
        )
        if active is not None:
            await self.cancel_turn(principal, active.turn_id)
        await self.engine.delete_session(context)
        await self.sessions.delete(principal, session_id)
        await asyncio.to_thread(self.repository.delete_session, session_id)
        from core.observability.runtime import global_telemetry

        await global_telemetry.flush()
        await asyncio.to_thread(
            global_telemetry.repository.delete_session, session_id
        )

    async def grant_high_risk_tool(
        self,
        principal: AuthenticatedPrincipal,
        *,
        session_id: str,
        tool_name: str,
        reason: str,
        ttl_s: float = 300,
    ) -> dict[str, Any]:
        await self.sessions.resolve(principal, session_id)
        from core.tool_registry import physical_tool_manager

        grant = physical_tool_manager.grant_high_risk_tool(
            session_id=session_id,
            tool_name=tool_name,
            granted_by=principal.user_id,
            reason=reason,
            ttl_s=ttl_s,
        )
        return grant.model_dump(mode="json")

    async def _emit_from_engine(
        self,
        turn_id: str,
        session_id: str,
        event_type: GatewayEventType,
        payload: dict,
    ) -> None:
        await self._emit(turn_id, session_id, event_type, payload)

    async def _emit(
        self,
        turn_id: str,
        session_id: str,
        event_type: GatewayEventType,
        payload: dict | None = None,
    ) -> GatewayEvent:
        event = await asyncio.to_thread(
            self.repository.append_event,
            turn_id=turn_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )
        dropped = self.events.publish(event)
        await asyncio.to_thread(self.repository.mark_delivered, event.event_id)
        if dropped:
            # The durable log remains the source of truth; reconnecting clients replay by sequence.
            pass
        return event

    async def health(self) -> GatewayHealth:
        repository = await asyncio.to_thread(self.repository.health)
        return GatewayHealth(
            status="ok" if self._started else "stopped",
            started=self._started,
            accepting_turns=self._accepting,
            active_turns=sum(not task.done() for task in self._turn_tasks.values()),
            subscribers=self.events.subscriber_count,
            database=repository["database"],
            pending_outbox=repository["pending_outbox"],
        )

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if not self._started:
                self.repository.close()
                return
            self._accepting = False
            tasks = [task for task in self._turn_tasks.values() if not task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.engine.close()
            self.repository.close()
            self._turn_tasks.clear()
            self._started = False
