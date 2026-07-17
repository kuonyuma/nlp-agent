import asyncio

import pytest

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.session_context import SessionContext
from gateway.contracts import (
    GatewayEventType,
    InjectMessageRequest,
    SubmitTurnRequest,
    TurnConflictError,
    TurnStatus,
)
from gateway.core import BackendGateway
from gateway.repository import GatewayRepository


class FakeSessions:
    def __init__(self):
        self.contexts = {}

    async def create(self, principal, *, workspace_id="default", channel="web"):
        principal.require_workspace(workspace_id)
        context = SessionContext.create(
            user_id=principal.user_id, workspace_id=workspace_id, channel=channel
        )
        self.contexts[context.session_id] = context
        return context

    async def resolve(self, principal, session_id):
        context = self.contexts[session_id]
        principal.require_context(context)
        return context

    async def delete(self, principal, session_id):
        context = await self.resolve(principal, session_id)
        self.contexts.pop(session_id)
        return context

    async def touch(self, principal, session_id):
        return await self.resolve(principal, session_id)


class FakeEngine:
    def __init__(self):
        self.sink = None
        self.block = None
        self.injected = []
        self.active = {}
        self.closed = False

    async def start(self, event_sink):
        self.sink = event_sink

    async def run_turn(self, context, turn_id, content):
        self.active[context.session_id] = turn_id
        await self.sink(
            turn_id,
            context.session_id,
            GatewayEventType.MESSAGE_DELTA,
            {"delta": "answer"},
        )
        if self.block is not None:
            await self.block.wait()
        self.active.pop(context.session_id, None)
        return f"final:{content}"

    async def inject(self, context, content):
        turn_id = self.active.get(context.session_id)
        if turn_id:
            self.injected.append(content)
        return turn_id

    async def cancel_turn(self, context, turn_id):
        self.active.pop(context.session_id, None)

    async def delete_session(self, context):
        self.active.pop(context.session_id, None)

    async def close(self):
        self.closed = True


@pytest.fixture
def principal():
    return AuthenticatedPrincipal(user_id="alice", workspace_ids=frozenset({"w1"}))


@pytest.mark.asyncio
async def test_gateway_runs_turn_replays_events_and_deduplicates(tmp_path, principal):
    engine = FakeEngine()
    sessions = FakeSessions()
    gateway = BackendGateway(
        engine=engine,
        repository=GatewayRepository(tmp_path / "gateway.sqlite3"),
        sessions=sessions,
    )
    await gateway.start()
    session = await gateway.create_session(principal, workspace_id="w1")
    request = SubmitTurnRequest(
        session_id=session.session_id, content="hello", idempotency_key="same"
    )
    accepted = await gateway.submit_turn(principal, request)
    events = [event async for event in gateway.stream_events(principal, accepted.turn_id)]

    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].type == GatewayEventType.TURN_COMPLETED
    turn = await gateway.get_turn(principal, accepted.turn_id)
    assert turn.status == TurnStatus.COMPLETED
    assert turn.final_text == "final:hello"

    duplicate = await gateway.submit_turn(principal, request)
    assert duplicate.duplicate is True
    assert duplicate.turn_id == accepted.turn_id
    await gateway.close()
    assert engine.closed is True


@pytest.mark.asyncio
async def test_gateway_enforces_single_turn_supports_injection_and_cancel(tmp_path, principal):
    engine = FakeEngine()
    engine.block = asyncio.Event()
    sessions = FakeSessions()
    gateway = BackendGateway(
        engine=engine,
        repository=GatewayRepository(tmp_path / "gateway.sqlite3"),
        sessions=sessions,
    )
    await gateway.start()
    session = await gateway.create_session(principal, workspace_id="w1")
    first = await gateway.submit_turn(
        principal, SubmitTurnRequest(session_id=session.session_id, content="slow")
    )
    while session.session_id not in engine.active:
        await asyncio.sleep(0)

    with pytest.raises(TurnConflictError):
        await gateway.submit_turn(
            principal, SubmitTurnRequest(session_id=session.session_id, content="second")
        )
    injected = await gateway.inject_message(
        principal,
        InjectMessageRequest(session_id=session.session_id, content="correction"),
    )
    assert injected.turn_id == first.turn_id
    assert engine.injected == ["correction"]

    cancelled = await gateway.cancel_turn(principal, first.turn_id)
    assert cancelled.status == TurnStatus.CANCELLED
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_denies_cross_user_turn_access(tmp_path, principal):
    gateway = BackendGateway(
        engine=FakeEngine(),
        repository=GatewayRepository(tmp_path / "gateway.sqlite3"),
        sessions=FakeSessions(),
    )
    await gateway.start()
    session = await gateway.create_session(principal, workspace_id="w1")
    accepted = await gateway.submit_turn(
        principal, SubmitTurnRequest(session_id=session.session_id, content="private")
    )
    bob = AuthenticatedPrincipal(user_id="bob", workspace_ids=frozenset({"w1"}))
    with pytest.raises(AccessDeniedError):
        await gateway.get_turn(bob, accepted.turn_id)
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_serializes_concurrent_turn_submission_per_session(tmp_path, principal):
    engine = FakeEngine()
    engine.block = asyncio.Event()
    sessions = FakeSessions()
    gateway = BackendGateway(
        engine=engine,
        repository=GatewayRepository(tmp_path / "gateway.sqlite3"),
        sessions=sessions,
    )
    await gateway.start()
    session = await gateway.create_session(principal, workspace_id="w1")

    results = await asyncio.gather(
        gateway.submit_turn(
            principal,
            SubmitTurnRequest(session_id=session.session_id, content="first"),
        ),
        gateway.submit_turn(
            principal,
            SubmitTurnRequest(session_id=session.session_id, content="second"),
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, TurnConflictError) for result in results) == 1
    await gateway.close()
