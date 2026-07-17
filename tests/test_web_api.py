import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.identity import AuthenticatedPrincipal
from core.session_context import SessionContext
from gateway.contracts import GatewayEventType
from gateway.core import BackendGateway
from gateway.repository import GatewayRepository
from server.web.app import create_app
from server.web.auth import SameOriginSessionAuth
from server.web.contracts import ServerEventEnvelope
from server.web.websocket import WebSocketConnection, WebSocketHub


class FakeSessions:
    def __init__(self):
        self.contexts = {}

    async def create(self, principal, *, workspace_id="default", channel="web"):
        principal.require_workspace(workspace_id)
        context = SessionContext.create(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            channel=channel,
        )
        self.contexts[context.session_id] = context
        return context

    async def resolve(self, principal, session_id):
        context = self.contexts.get(session_id)
        if context is None:
            raise FileNotFoundError(session_id)
        principal.require_context(context)
        return context

    async def list(self, principal):
        return [
            context.model_dump(mode="json")
            for context in self.contexts.values()
            if principal.can_access(context)
        ]

    async def messages(self, principal, session_id):
        await self.resolve(principal, session_id)
        return []

    async def touch(self, principal, session_id):
        return await self.resolve(principal, session_id)

    async def delete(self, principal, session_id):
        context = await self.resolve(principal, session_id)
        self.contexts.pop(session_id)
        return context


class FakeEngine:
    def __init__(self):
        self.sink = None
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
            {"delta": "thinking", "channel": "reasoning"},
        )
        await self.sink(
            turn_id,
            context.session_id,
            GatewayEventType.TOOL_STARTED,
            {"tool_name": "demo"},
        )
        await self.sink(
            turn_id,
            context.session_id,
            GatewayEventType.MESSAGE_DELTA,
            {"delta": f"answer:{content}"},
        )
        await self.sink(
            turn_id,
            context.session_id,
            GatewayEventType.TOOL_COMPLETED,
            {"tool_name": "demo"},
        )
        self.active.pop(context.session_id, None)
        return f"answer:{content}"

    async def inject(self, context, content):
        return self.active.get(context.session_id)

    async def cancel_turn(self, context, turn_id):
        self.active.pop(context.session_id, None)

    async def delete_session(self, context):
        self.active.pop(context.session_id, None)

    async def close(self):
        self.closed = True


@pytest.fixture
def web_app(tmp_path):
    engine = FakeEngine()
    sessions = FakeSessions()

    def gateway_factory():
        return BackendGateway(
            engine=engine,
            repository=GatewayRepository(tmp_path / "gateway.sqlite3"),
            sessions=sessions,
        )

    auth = SameOriginSessionAuth(
        secret="test-secret-that-is-long-enough-for-hmac",
        allowed_origins=["http://testserver"],
    )
    return create_app(gateway_factory=gateway_factory, auth=auth), engine


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/session",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"]


def write_headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def test_http_lifecycle_sessions_chat_settings_and_csrf(web_app):
    app, engine = web_app
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").status_code == 200
        csrf = authenticate(client)

        rejected = client.post("/api/v1/sessions", json={"workspace_id": "default"})
        assert rejected.status_code == 403
        assert rejected.json()["code"] == "origin_rejected"

        created = client.post(
            "/api/v1/sessions",
            json={"workspace_id": "default"},
            headers=write_headers(csrf),
        )
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        assert client.get("/api/v1/sessions").json()["items"][0]["session_id"] == session_id

        accepted = client.post(
            "/api/v1/chat/turns",
            json={"session_id": session_id, "content": "hello", "idempotency_key": "one"},
            headers=write_headers(csrf),
        )
        assert accepted.status_code == 202
        turn_id = accepted.json()["turn_id"]

        for _ in range(100):
            turn = client.get(f"/api/v1/chat/turns/{turn_id}").json()
            if turn["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.001))
        assert turn["final_text"] == "answer:hello"
        events = client.get(f"/api/v1/chat/turns/{turn_id}/events").json()["items"]
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))

        updated = client.patch(
            "/api/v1/settings",
            json={"theme": "dark", "show_reasoning": True},
            headers=write_headers(csrf),
        )
        assert updated.json()["revision"] == 1
        assert client.get("/api/v1/settings").json()["preferences"]["settings"]["theme"] == "dark"

        deleted = client.delete(
            f"/api/v1/sessions/{session_id}",
            headers=write_headers(csrf),
        )
        assert deleted.status_code == 204
    assert engine.closed is True


def _receive_until(websocket, required_types: set[str], limit: int = 30):
    events = []
    seen = set()
    for _ in range(limit):
        event = websocket.receive_json()
        events.append(event)
        seen.add(event["type"])
        if required_types <= seen:
            return events
    raise AssertionError(f"missing event types: {required_types - seen}; got={seen}")


def test_websocket_multiplex_stream_and_resume(web_app):
    app, _engine = web_app
    with TestClient(app) as client:
        csrf = authenticate(client)
        session_id = client.post(
            "/api/v1/sessions",
            json={"workspace_id": "default"},
            headers=write_headers(csrf),
        ).json()["session_id"]

        with client.websocket_connect(
            "/ws/v1",
            headers={"Origin": "http://testserver"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "connection.ready"
            websocket.send_json(
                {
                    "v": "1",
                    "type": "chat.send",
                    "request_id": "send-1",
                    "payload": {"session_id": session_id, "content": "over ws"},
                }
            )
            events = _receive_until(
                websocket,
                {
                    "command.ack",
                    "chat.accepted",
                    "chat.started",
                    "chat.reasoning.delta",
                    "tool.started",
                    "chat.delta",
                    "tool.completed",
                    "chat.completed",
                },
            )
            turn_id = next(event["turn_id"] for event in events if event["type"] == "command.ack")
            sequenced = [event["sequence"] for event in events if "sequence" in event]
            assert sequenced == sorted(set(sequenced))

        with client.websocket_connect(
            "/ws/v1",
            headers={"Origin": "http://testserver"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "connection.ready"
            websocket.send_json(
                {
                    "v": "1",
                    "type": "stream.resume",
                    "request_id": "resume-1",
                    "payload": {"turn_id": turn_id, "after_sequence": 0},
                }
            )
            replayed = _receive_until(websocket, {"command.ack", "chat.completed"})
            sequences = [event["sequence"] for event in replayed if "sequence" in event]
            assert sequences == list(range(1, max(sequences) + 1))


def test_websocket_rejects_cross_origin(web_app):
    app, _engine = web_app
    with TestClient(app) as client:
        authenticate(client)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/v1",
                headers={"Origin": "https://evil.example"},
            ) as websocket:
                websocket.receive_json()
        assert exc.value.code == 4403


class SlowWebSocket:
    def __init__(self):
        self.block = asyncio.Event()
        self.closed = []

    async def send_json(self, _payload):
        await self.block.wait()

    async def close(self, *, code, reason):
        self.closed.append((code, reason))


@pytest.mark.asyncio
async def test_websocket_slow_sender_is_disconnected_without_blocking_publish():
    websocket = SlowWebSocket()
    principal = AuthenticatedPrincipal(
        user_id="slow-user", workspace_ids=frozenset({"default"})
    )
    connection = WebSocketConnection(
        websocket,
        gateway=None,
        principal=principal,
        max_queue=10,
        send_queue_size=1,
        send_timeout_s=0.1,
    )
    connection.start()
    event = ServerEventEnvelope(type="test.event", payload={})

    assert await connection.send(event) is True
    await asyncio.wait_for(connection.wait_closed(), timeout=0.5)

    assert websocket.closed[0][0] == 1013


def test_websocket_hub_enforces_global_and_per_user_limits():
    alice = AuthenticatedPrincipal(user_id="alice")
    bob = AuthenticatedPrincipal(user_id="bob")
    hub = WebSocketHub(max_connections=2, max_connections_per_user=1)

    def connection(principal):
        return WebSocketConnection(
            SlowWebSocket(),
            gateway=None,
            principal=principal,
            max_queue=10,
            send_queue_size=1,
            send_timeout_s=0.1,
        )

    assert hub.try_add(connection(alice)) is True
    assert hub.try_add(connection(alice)) is False
    assert hub.try_add(connection(bob)) is True
    assert hub.try_add(connection(AuthenticatedPrincipal(user_id="carol"))) is False
