from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core.observability.context import TelemetryContext
from core.observability.models import TokenUsage
from core.observability.runtime import TelemetryRuntime
from server.monitor.app import create_monitor_app
from server.monitor.reset import _clear_directory
from server.web.auth import SameOriginSessionAuth


class ResetSpy:
    calls = 0

    async def reset(self):
        self.calls += 1
        return {"sessions": 1, "gateway": {}, "telemetry": {}, "files": {}}


def test_reset_cleanup_keeps_active_checkpoint_database_and_removes_orphans(tmp_path):
    checkpoint = tmp_path / "coordinator_memory.sqlite3"
    checkpoint.write_text("active", encoding="utf-8")
    (tmp_path / "coordinator_memory.sqlite3-wal").write_text("wal", encoding="utf-8")
    (tmp_path / "coordinator_memory.sqlite3-shm").write_text("shm", encoding="utf-8")
    orphan = tmp_path / "completed-worker.json"
    orphan.write_text("remove", encoding="utf-8")

    removed = _clear_directory(
        tmp_path,
        preserve_names={
            "coordinator_memory.sqlite3",
            "coordinator_memory.sqlite3-wal",
            "coordinator_memory.sqlite3-shm",
        },
    )

    assert removed == 1
    assert checkpoint.exists()
    assert not orphan.exists()


def test_monitor_is_admin_only_and_queries_observability(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    context = TelemetryContext.create(session_id="session-monitor", turn_id="turn-monitor")
    runtime.start_trace(context)
    runtime.complete_trace(
        context,
        usage=TokenUsage(input_tokens=10, output_tokens=4, total_tokens=14, source="provider"),
    )
    auth = SameOriginSessionAuth(
        secret="monitor-test-secret",
        cookie_name="monitor_test",
        allowed_origins=["http://testserver"],
    )
    resetter = ResetSpy()
    app = create_monitor_app(runtime=runtime, auth=auth, resetter=resetter)  # type: ignore[arg-type]
    with TestClient(app) as client:
        assert client.get("/api/v1/observability/overview").status_code == 401
        login = client.post("/api/v1/auth/session", headers={"Origin": "http://testserver"})
        assert login.status_code == 201
        overview = client.get("/api/v1/observability/overview").json()
        assert overview["requests"] == 1
        assert overview["tokens"]["total_tokens"] == 14
        traces = client.get("/api/v1/observability/traces").json()["items"]
        assert traces[0]["trace_id"] == context.trace_id
        detail = client.get(f"/api/v1/observability/traces/{context.trace_id}").json()
        assert detail["trace"]["session_id"] == "session-monitor"
        rejected = client.post("/api/v1/observability/storage/prune?trace_days=30&event_days=30")
        assert rejected.status_code == 403
        accepted = client.post(
            "/api/v1/observability/storage/prune?trace_days=30&event_days=30",
            headers={"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert accepted.status_code == 200
        reset = client.post(
            "/api/v1/observability/storage/reset",
            headers={"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert reset.status_code == 200
        assert reset.json()["sessions"] == 1
        assert resetter.calls == 1


@pytest.mark.asyncio
async def test_monitor_live_events_ignores_a_client_that_disconnects_during_heartbeat(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    auth = SameOriginSessionAuth(
        secret="monitor-test-secret",
        cookie_name="monitor_test",
        allowed_origins=["http://testserver"],
    )
    app = create_monitor_app(runtime=runtime, auth=auth, resetter=ResetSpy())  # type: ignore[arg-type]
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ws/observability")
    token, _claims = auth.issue()

    class DisconnectingWebSocket:
        headers = {"origin": "http://testserver", "host": "testserver"}
        cookies = {"monitor_test": token}
        accepted = False

        async def accept(self):
            self.accepted = True

        async def send_json(self, _payload):
            raise WebSocketDisconnect(code=1006)

        async def close(self, **_kwargs):
            return None

    websocket = DisconnectingWebSocket()
    await endpoint(websocket)

    assert websocket.accepted is True
    await runtime.close()
