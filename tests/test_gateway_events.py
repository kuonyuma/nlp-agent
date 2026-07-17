from gateway.contracts import GatewayEvent, GatewayEventType
from gateway.events import GatewayEventBroker


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
