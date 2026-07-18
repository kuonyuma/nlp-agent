from fastapi.testclient import TestClient

from core.observability.context import TelemetryContext
from core.observability.models import TokenUsage
from core.observability.runtime import TelemetryRuntime
from server.monitor.app import create_monitor_app
from server.web.auth import SameOriginSessionAuth


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
    app = create_monitor_app(runtime=runtime, auth=auth)
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
