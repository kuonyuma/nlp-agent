import asyncio

from core.observability.context import TelemetryContext, bind_telemetry_context
from core.observability.models import SpanKind, SpanStatus, TokenUsage
from core.observability.runtime import TelemetryRuntime
from core.observability.service import ObservabilityService


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

    overview = await service.overview()
    assert overview["requests"] == 1
    assert overview["successes"] == 1
    assert overview["tokens"]["total_tokens"] == 15

    traces = await service.traces(session_id="session-1")
    assert traces[0]["trace_id"] == context.trace_id
    detail = await service.trace(context.trace_id)
    assert detail is not None
    assert detail["spans"][0]["parent_span_id"] == context.span_id
    assert detail["events"][0]["name"] == "model.response"
    usage = await service.usage()
    assert usage[0]["total_tokens"] == 15
    await runtime.close()


async def test_error_aggregation_and_live_subscription(tmp_path):
    runtime = TelemetryRuntime(tmp_path / "telemetry.sqlite3", flush_interval_s=0.01)
    service = ObservabilityService(runtime)
    context = TelemetryContext.create(session_id="session-2", turn_id="turn-2")
    queue = service.subscribe()

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
    errors = await service.errors()
    assert errors[0]["error_kind"] == "timeout"
    assert errors[0]["count"] == 1
    service.unsubscribe(queue)
    await runtime.close()
