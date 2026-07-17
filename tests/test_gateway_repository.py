from gateway.contracts import GatewayEventType, TurnStatus
from gateway.repository import GatewayRepository


def test_gateway_repository_idempotency_event_order_and_recovery(tmp_path):
    repository = GatewayRepository(tmp_path / "gateway.sqlite3")
    turn, duplicate = repository.create_turn(
        turn_id="turn-1",
        session_id="session-1",
        workspace_id="workspace-1",
        user_id="alice",
        input_text="hello",
        idempotency_key="idem-1",
    )
    assert duplicate is False
    same, duplicate = repository.create_turn(
        turn_id="turn-other",
        session_id="session-1",
        workspace_id="workspace-1",
        user_id="alice",
        input_text="hello again",
        idempotency_key="idem-1",
    )
    assert duplicate is True
    assert same.turn_id == turn.turn_id

    repository.update_turn(turn.turn_id, TurnStatus.RUNNING)
    first = repository.append_event(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        event_type=GatewayEventType.TURN_STARTED,
    )
    second = repository.append_event(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        event_type=GatewayEventType.MESSAGE_DELTA,
        payload={"delta": "hi"},
    )
    assert [event.sequence for event in repository.events_after(turn.turn_id)] == [1, 2]
    assert {event.event_id for event in repository.pending_outbox()} == {
        first.event_id,
        second.event_id,
    }

    recovered = repository.recover_interrupted()
    assert recovered[0].status == TurnStatus.INTERRUPTED
    repository.close()
