import asyncio
import time

import pytest

from core.worker_events import WorkerCompletedEvent, WorkerEventBus
from schemas.models import WorkerExecutionResultSpec, WorkerTimingSpec


def make_event(event_id="event-1"):
    now = time.time()
    return WorkerCompletedEvent.create(
        event_id=event_id,
        session_id="session-a",
        worker_id="worker-a",
        parent_turn_id="turn-a",
        attempt=1,
        execution=WorkerExecutionResultSpec(
            status="completed",
            summary="done",
            output="result",
            timing=WorkerTimingSpec(started_at=now, completed_at=now, duration_ms=0),
            termination_reason="completed",
        ),
        join=True,
    )


@pytest.mark.asyncio
async def test_event_bus_deduplicates_and_notifies_multiple_subscribers():
    bus = WorkerEventBus()
    notified = []
    bus.subscribe(lambda session_id: notified.append(("all", session_id)))
    bus.subscribe(lambda session_id: notified.append(("session", session_id)), "session-a")

    assert await bus.publish(make_event()) is True
    assert await bus.publish(make_event()) is False
    await asyncio.sleep(0)

    assert notified == [("all", "session-a"), ("session", "session-a")]
    assert bus.metrics_snapshot()["duplicate_events"] == 1


@pytest.mark.asyncio
async def test_event_bus_applies_bounded_queue_backpressure():
    bus = WorkerEventBus(max_events_per_session=1, publish_timeout_s=0.01)
    await bus.publish(make_event("first"))
    with pytest.raises(RuntimeError, match="queue is full"):
        await bus.publish(make_event("second"))
    assert bus.metrics_snapshot()["publish_timeouts"] == 1
