import asyncio
import pytest

from core.observability.context import TelemetryContext, bind_telemetry_context
from core.observability.models import SpanKind, SpanStatus, TokenUsage
from core.observability.runtime import TelemetryRuntime
from core.observability.service import ObservabilityService
from core.identity import AuthenticatedPrincipal
from core.identity import AccessDeniedError


ADMIN = AuthenticatedPrincipal.system_admin()


async def test_trace_span_usage_and_queries(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    service = ObservabilityService(runtime)
    context = TelemetryContext.create(
        session_id="session-1", turn_id="turn-1", workspace_id="workspace-1"
    )

    runtime.start_trace(context)
    with bind_telemetry_context(context):
        async with runtime.span(
            SpanKind.MODEL, "coordinator.model", attributes={"model": "test-model"}
        ) as span:
            span.set_usage(TokenUsage(
                input_tokens=12, output_tokens=3, total_tokens=15, source="provider"
            ))
            runtime.event("model.response", payload={"finish_reason": "stop"})
        runtime.mark_ttft()
    runtime.complete_trace(context)
    await runtime.flush()

    overview = await service.overview(ADMIN)
    assert overview["requests"] == 1
    assert overview["successes"] == 1
    assert overview["tokens"]["total_tokens"] == 15

    traces = await service.traces(ADMIN, session_id="session-1")
    assert traces[0]["trace_id"] == context.trace_id
    detail = await service.trace(ADMIN, context.trace_id)
    assert detail is not None
    assert detail["spans"][0]["parent_span_id"] == context.span_id
    assert detail["events"][0]["name"] == "model.response"
    usage = await service.usage(ADMIN)
    assert usage[0]["total_tokens"] == 15
    await runtime.close()


async def test_error_aggregation_and_live_subscription(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    service = ObservabilityService(runtime)
    context = TelemetryContext.create(session_id="session-2", turn_id="turn-2")
    queue = service.subscribe(ADMIN)

    runtime.start_trace(context)
    with bind_telemetry_context(context):
        async with runtime.span(SpanKind.TOOL, "tool.search") as span:
            span.set_status(
                SpanStatus.TIMEOUT, error_kind="timeout", error_message="request timed out"
            )
    runtime.complete_trace(context, status=SpanStatus.ERROR)
    await runtime.flush()

    live = await asyncio.wait_for(queue.get(), timeout=1)
    assert live["kind"] == "trace"
    errors = await service.errors(ADMIN)
    assert errors[0]["error_kind"] == "timeout"
    assert errors[0]["count"] == 1
    service.unsubscribe(queue)
    await runtime.close()


async def test_observability_queries_are_scoped_to_principal(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    service = ObservabilityService(runtime)
    context = TelemetryContext.create(
        session_id="private-session",
        turn_id="turn-private",
        workspace_id="w1",
        user_id="alice",
    )
    runtime.start_trace(context)
    runtime.complete_trace(context)
    await runtime.flush()

    alice = AuthenticatedPrincipal(user_id="alice", workspace_ids=frozenset({"w1"}))
    bob = AuthenticatedPrincipal(user_id="bob", workspace_ids=frozenset({"w1"}))
    assert len(await service.traces(alice)) == 1
    assert await service.traces(bob) == []
    with pytest.raises(AccessDeniedError):
        await service.trace(bob, context.trace_id)
    await runtime.close()


def test_runtime_moves_pending_events_to_a_replacement_event_loop(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=60)

    async def emit_without_flush():
        runtime.event("loop.one")

    asyncio.run(emit_without_flush())
    asyncio.run(runtime.flush())

    assert runtime.repository.health()["events"] == 1
    asyncio.run(runtime.close())
