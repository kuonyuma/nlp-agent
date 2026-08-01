import pytest

from gateway.contracts import GatewayEvent, GatewayEventType
from gateway.events import GatewayEventBroker, GatewayEventStreamInterrupted


def test_live_queue_keeps_latest_event_when_full():
    broker = GatewayEventBroker()
    _subscription_id, queue = broker.subscribe(turn_id="turn-1", maxsize=1)
    first = GatewayEvent(
        event_id="event-1",
        turn_id="turn-1",
        session_id="session-1",
        sequence=1,
        type=GatewayEventType.MESSAGE_DELTA,
    )
    terminal = GatewayEvent(
        event_id="event-2",
        turn_id="turn-1",
        session_id="session-1",
        sequence=2,
        type=GatewayEventType.TURN_COMPLETED,
    )

    assert broker.publish(first) == 0
    assert broker.publish(terminal) == 1
    assert queue.get_nowait() == terminal


async def test_interrupt_all_requires_subscribers_to_replay_durable_events():
    broker = GatewayEventBroker()
    subscription = broker.open_subscription(session_id="session-1")

    assert broker.interrupt_all() == 1
    with pytest.raises(GatewayEventStreamInterrupted):
        await subscription.__anext__()
