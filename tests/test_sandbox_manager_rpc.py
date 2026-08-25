from __future__ import annotations

import asyncio
import json
import time


def test_manager_rpc_client_round_trips_signed_request() -> None:
    from server.sandbox.manager_rpc import RedisSandboxManagerRpcClient

    class FakeRedis:
        def __init__(self) -> None:
            self.response_stream = ""

        async def xadd(self, stream, fields, **_kwargs):
            if stream.startswith("nova:sandbox:manager:rpc:responses:"):
                self.response_stream = stream
            else:
                self.response_stream = fields["response_stream"]

        async def xread(self, streams, **_kwargs):
            stream = next(iter(streams))
            if stream != self.response_stream:
                return []
            return [
                (
                    stream,
                    [
                        (
                            "1-0",
                            {
                                "request_id": stream.rsplit(":", 1)[-1],
                                "ok": "1",
                                "payload": json.dumps({"status": "completed"}),
                                "error": "",
                            },
                        )
                    ],
                )
            ]

    async def exercise() -> dict[str, object]:
        client = RedisSandboxManagerRpcClient(FakeRedis(), secret="rpc-secret", timeout_seconds=1)
        return await client.run_scratch(source="print(1)")

    assert asyncio.run(exercise()) == {"status": "completed"}


def test_manager_rpc_server_dispatches_claim_without_docker_in_web_process() -> None:
    from datetime import UTC, datetime, timedelta
    from server.sandbox.contracts import SandboxScope
    from server.sandbox.manager_rpc import RedisSandboxManagerRpcServer

    class FakeManager:
        async def claim(self, _scope, *, lease_id):
            assert lease_id == "lease-1"
            from server.sandbox.manager_rpc import RemoteRuntime, RemoteRuntimeClaim

            return RemoteRuntimeClaim(
                runtime=RemoteRuntime("runtime-1", 4, "environment-1", "docker-1"),
                nonce="nonce-1",
            )

    class FakeRedis:
        def __init__(self) -> None:
            self.done = False
            self.response: dict[str, str] | None = None

        async def xread(self, _streams, **_kwargs):
            if self.done:
                return []
            self.done = True
            scope = SandboxScope(
                owner_user_id="user-1",
                auth_session_id="session-1",
                workspace_id="workspace-1",
                generation=1,
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            from server.sandbox.manager_rpc import _json, _scope_payload, _signature

            now = time.time()
            payload = _json({
                "scope": _scope_payload(scope),
                "lease_id": "lease-1",
                "issued_at": now,
                "expires_at": now + 60,
            })
            return [
                (
                    "nova:sandbox:manager:rpc:requests",
                    [
                        (
                            "1-0",
                            {
                                "request_id": "request-1",
                                "response_stream": "nova:sandbox:manager:rpc:responses:request-1",
                                "method": "claim",
                                "payload": payload,
                                "signature": _signature("rpc-secret", "request-1", "claim", payload),
                            },
                        )
                    ],
                )
            ]

        async def xadd(self, _stream, fields, **_kwargs):
            self.response = fields

        async def expire(self, *_args):
            return True

    async def exercise() -> dict[str, str]:
        redis = FakeRedis()
        server = RedisSandboxManagerRpcServer(redis, manager=FakeManager(), secret="rpc-secret")
        assert await server.process_once(block_ms=1)
        await asyncio.sleep(0)
        assert redis.response is not None
        return redis.response

    response = asyncio.run(exercise())
    assert response["ok"] == "1"
    assert json.loads(response["payload"])["claim"]["runtime"]["generation"] == 4


def test_manager_rpc_server_rejects_expired_requests_after_restart() -> None:
    """A restarted Manager must not replay stale requests from the stream."""
    from server.sandbox.manager_rpc import RedisSandboxManagerRpcServer

    class FakeManager:
        called = False

        async def capacity_snapshot(self):
            self.called = True
            return {"target": 1}

    class FakeRedis:
        def __init__(self) -> None:
            self.response: dict[str, str] | None = None

        async def xadd(self, _stream, fields, **_kwargs):
            self.response = fields

        async def expire(self, *_args):
            return True

    async def exercise() -> dict[str, str]:
        from server.sandbox.manager_rpc import _json, _signature

        request_id = "expired-request"
        body = _json({
            "issued_at": time.time() - 120,
            "expires_at": time.time() - 60,
        })
        fields = {
            "request_id": request_id,
            "response_stream": "nova:sandbox:manager:rpc:responses:expired-request",
            "method": "capacity_snapshot",
            "payload": body,
            "signature": _signature("rpc-secret", request_id, "capacity_snapshot", body),
        }
        redis = FakeRedis()
        manager = FakeManager()
        server = RedisSandboxManagerRpcServer(redis, manager=manager, secret="rpc-secret")
        await server._handle(fields)
        assert manager.called is False
        assert redis.response is not None
        return redis.response

    response = asyncio.run(exercise())
    assert response["ok"] == "0"
    assert "expired" in response["error"]
