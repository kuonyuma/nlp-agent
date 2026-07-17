"""Multiplexed WebSocket command channel backed only by BackendGateway APIs."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from core.identity import AuthenticatedPrincipal
from gateway.contracts import GatewayEventType, InjectMessageRequest, SubmitTurnRequest
from gateway.core import BackendGateway
from gateway.events import GatewayEventSubscription
from server.web.auth import AuthenticationError, OriginRejectedError, SameOriginSessionAuth
from server.web.contracts import (
    ChatCancelPayload,
    ChatInjectPayload,
    ChatSendPayload,
    CommandEnvelope,
    PingPayload,
    ServerEventEnvelope,
    SessionSubscriptionPayload,
    StreamResumePayload,
    parse_command_payload,
)
from server.web.protocol import control_event, gateway_event_envelope


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: set[WebSocketConnection] = set()

    def add(self, connection: "WebSocketConnection") -> None:
        self._connections.add(connection)

    def discard(self, connection: "WebSocketConnection") -> None:
        self._connections.discard(connection)

    async def broadcast(
        self,
        event: ServerEventEnvelope,
        *,
        user_id: str | None = None,
    ) -> None:
        targets = [
            connection
            for connection in tuple(self._connections)
            if user_id is None or connection.principal.user_id == user_id
        ]
        if targets:
            await asyncio.gather(
                *(connection.send(event) for connection in targets),
                return_exceptions=True,
            )

    async def close(self) -> None:
        connections = list(self._connections)
        self._connections.clear()
        if connections:
            await asyncio.gather(
                *(
                    connection.send(
                        control_event(
                            "server.shutdown",
                            payload={"reason": "service_restart"},
                        )
                    )
                    for connection in connections
                ),
                return_exceptions=True,
            )
        for connection in connections:
            try:
                await connection.websocket.close(code=1012, reason="service restart")
            except RuntimeError:
                pass
            await connection.close()


class WebSocketConnection:
    def __init__(
        self,
        websocket: WebSocket,
        gateway: BackendGateway,
        principal: AuthenticatedPrincipal,
        *,
        max_queue: int,
    ) -> None:
        self.websocket = websocket
        self.gateway = gateway
        self.principal = principal
        self.max_queue = max_queue
        self._subscriptions: dict[str, GatewayEventSubscription] = {}
        self._subscription_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_sequences: dict[str, int] = {}
        self._turn_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def send(self, event: ServerEventEnvelope) -> None:
        if self._closed:
            return
        async with self._send_lock:
            await self.websocket.send_json(event.model_dump(mode="json", exclude_none=True))

    async def subscribe(self, session_id: str) -> bool:
        if session_id in self._subscriptions:
            return False
        subscription = await self.gateway.subscribe_session_events(
            self.principal,
            session_id,
            max_queue=self.max_queue,
        )
        self._subscriptions[session_id] = subscription
        self._subscription_tasks[session_id] = asyncio.create_task(
            self._pump_session(session_id, subscription),
            name=f"websocket-session:{session_id}",
        )
        return True

    async def unsubscribe(self, session_id: str) -> bool:
        subscription = self._subscriptions.pop(session_id, None)
        task = self._subscription_tasks.pop(session_id, None)
        if subscription is None:
            return False
        await subscription.close()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return True

    async def _pump_session(
        self,
        session_id: str,
        subscription: GatewayEventSubscription,
    ) -> None:
        try:
            async for event in subscription:
                await self._deliver_gateway_event(event)
        except asyncio.CancelledError:
            raise
        finally:
            await subscription.close()
            if self._subscriptions.get(session_id) is subscription:
                self._subscriptions.pop(session_id, None)
                self._subscription_tasks.pop(session_id, None)

    async def replay_turn(self, turn_id: str, after_sequence: int) -> int:
        latest = await self.gateway.latest_event_sequence(self.principal, turn_id)
        if after_sequence > latest:
            raise ValueError(
                f"after_sequence {after_sequence} exceeds latest sequence {latest}"
            )
        lock = self._turn_locks[turn_id]
        async with lock:
            self._last_sequences[turn_id] = max(
                self._last_sequences.get(turn_id, 0),
                after_sequence,
            )
            return await self._replay_locked(turn_id, latest)

    async def _replay_locked(self, turn_id: str, target_sequence: int) -> int:
        sent = 0
        while self._last_sequences.get(turn_id, 0) < target_sequence:
            after = self._last_sequences.get(turn_id, 0)
            events = await self.gateway.replay_events(
                self.principal,
                turn_id,
                after_sequence=after,
                limit=min(2_000, target_sequence - after),
            )
            if not events:
                break
            for event in events:
                if event.sequence > target_sequence:
                    break
                await self._send_gateway_event_locked(event)
                sent += 1
        return sent

    async def _deliver_gateway_event(self, event: Any) -> None:
        lock = self._turn_locks[event.turn_id]
        async with lock:
            last = self._last_sequences.get(event.turn_id, 0)
            if event.sequence <= last:
                return
            if event.sequence > last + 1:
                await self._replay_locked(event.turn_id, event.sequence - 1)
                last = self._last_sequences.get(event.turn_id, 0)
                if event.sequence > last + 1:
                    await self.send(
                        control_event(
                            "stream.gap",
                            session_id=event.session_id,
                            turn_id=event.turn_id,
                            payload={
                                "expected_sequence": last + 1,
                                "received_sequence": event.sequence,
                            },
                        )
                    )
            await self._send_gateway_event_locked(event)

    async def _send_gateway_event_locked(self, event: Any) -> None:
        if event.sequence <= self._last_sequences.get(event.turn_id, 0):
            return
        self._last_sequences[event.turn_id] = event.sequence
        await self.send(gateway_event_envelope(event))
        if event.type in {
            GatewayEventType.TURN_COMPLETED,
            GatewayEventType.TURN_FAILED,
            GatewayEventType.TURN_CANCELLED,
        }:
            await self.send(
                control_event(
                    "session.updated",
                    session_id=event.session_id,
                    turn_id=event.turn_id,
                    payload={"scope": "thread"},
                )
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscriptions = list(self._subscriptions.values())
        tasks = list(self._subscription_tasks.values())
        self._subscriptions.clear()
        self._subscription_tasks.clear()
        for subscription in subscriptions:
            await subscription.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _command_error(error: Exception) -> tuple[str, str]:
    name = type(error).__name__
    if isinstance(error, ValidationError):
        return "validation_error", "command payload is invalid"
    if isinstance(error, ValueError):
        return "invalid_command", str(error)
    if isinstance(error, FileNotFoundError):
        return "not_found", str(error)
    if isinstance(error, PermissionError):
        return "forbidden", "resource access is forbidden"
    if name == "TurnConflictError":
        return "turn_conflict", str(error)
    if name == "ResourceNotFoundError":
        return "not_found", str(error)
    if name == "GatewayNotStartedError":
        return "gateway_unavailable", "Backend Gateway is not ready"
    return "internal_error", "command failed"


async def _dispatch_command(
    connection: WebSocketConnection,
    command: CommandEnvelope,
) -> None:
    payload = parse_command_payload(command)
    if isinstance(payload, ChatSendPayload):
        await connection.subscribe(payload.session_id)
        accepted = await connection.gateway.submit_turn(
            connection.principal,
            SubmitTurnRequest(
                session_id=payload.session_id,
                content=payload.content,
                idempotency_key=payload.idempotency_key,
            ),
        )
        await connection.send(
            control_event(
                "command.ack",
                request_id=command.request_id,
                session_id=accepted.session_id,
                turn_id=accepted.turn_id,
                payload={
                    "command": command.type,
                    "status": accepted.status.value,
                    "duplicate": accepted.duplicate,
                },
            )
        )
        if accepted.duplicate:
            await connection.replay_turn(accepted.turn_id, 0)
        return
    if isinstance(payload, ChatInjectPayload):
        accepted = await connection.gateway.inject_message(
            connection.principal,
            InjectMessageRequest(session_id=payload.session_id, content=payload.content),
        )
        await connection.send(
            control_event(
                "command.ack",
                request_id=command.request_id,
                session_id=accepted.session_id,
                turn_id=accepted.turn_id,
                payload={"command": command.type},
            )
        )
        return
    if isinstance(payload, ChatCancelPayload):
        turn = await connection.gateway.cancel_turn(connection.principal, payload.turn_id)
        await connection.send(
            control_event(
                "command.ack",
                request_id=command.request_id,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                payload={"command": command.type, "status": turn.status.value},
            )
        )
        return
    if isinstance(payload, SessionSubscriptionPayload):
        if command.type == "session.subscribe":
            changed = await connection.subscribe(payload.session_id)
        else:
            changed = await connection.unsubscribe(payload.session_id)
        await connection.send(
            control_event(
                "command.ack",
                request_id=command.request_id,
                session_id=payload.session_id,
                payload={"command": command.type, "changed": changed},
            )
        )
        return
    if isinstance(payload, StreamResumePayload):
        turn = await connection.gateway.get_turn(connection.principal, payload.turn_id)
        await connection.subscribe(turn.session_id)
        replayed = await connection.replay_turn(payload.turn_id, payload.after_sequence)
        await connection.send(
            control_event(
                "command.ack",
                request_id=command.request_id,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                payload={"command": command.type, "replayed": replayed},
            )
        )
        return
    if isinstance(payload, PingPayload):
        await connection.send(
            control_event(
                "pong",
                request_id=command.request_id,
                payload={"nonce": payload.nonce},
            )
        )


async def websocket_endpoint(
    websocket: WebSocket,
    *,
    gateway: BackendGateway,
    auth: SameOriginSessionAuth,
    hub: WebSocketHub,
    max_message_bytes: int,
    max_queue: int,
) -> None:
    try:
        auth.require_same_origin(websocket.headers.get("origin"), websocket.headers.get("host"))
        claims = auth.authenticate(websocket.cookies.get(auth.cookie_name))
    except AuthenticationError:
        await websocket.close(code=4401, reason="authentication required")
        return
    except OriginRejectedError:
        await websocket.close(code=4403, reason="origin rejected")
        return

    await websocket.accept()
    connection = WebSocketConnection(
        websocket,
        gateway,
        claims.principal(),
        max_queue=max_queue,
    )
    hub.add(connection)
    await connection.send(
        control_event(
            "connection.ready",
            payload={
                "user_id": claims.user_id,
                "workspace_ids": sorted(claims.workspace_ids),
                "protocol_version": "1",
            },
        )
    )
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > max_message_bytes:
                await websocket.close(code=1009, reason="message too large")
                return
            request_id: str | None = None
            try:
                command = CommandEnvelope.model_validate(json.loads(raw))
                request_id = command.request_id
                await _dispatch_command(connection, command)
            except (json.JSONDecodeError, ValidationError, ValueError, PermissionError, RuntimeError, LookupError) as error:
                code, message = _command_error(error)
                await connection.send(
                    control_event(
                        "command.error",
                        request_id=request_id,
                        payload={"code": code, "message": message},
                    )
                )
    except WebSocketDisconnect:
        pass
    finally:
        hub.discard(connection)
        await connection.close()
