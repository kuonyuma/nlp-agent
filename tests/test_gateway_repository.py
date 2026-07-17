from datetime import datetime, timedelta, timezone

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
    assert repository.health()["durable_events"] == 2
    assert repository._conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='gateway_outbox'"
    ).fetchone()[0] == 0

    recovered = repository.recover_interrupted()
    assert recovered[0].status == TurnStatus.INTERRUPTED
    repository.close()


def test_event_retention_compacts_terminal_turns_caps_sessions_and_keeps_active(tmp_path):
    repository = GatewayRepository(tmp_path / "gateway.sqlite3")
    terminal_ids = []
    for index in range(2):
        turn, _ = repository.create_turn(
            turn_id=f"terminal-{index}",
            session_id="session-1",
            workspace_id="workspace-1",
            user_id="alice",
            input_text="done",
            idempotency_key=None,
        )
        terminal_ids.append(turn.turn_id)
        repository.update_turn(turn.turn_id, TurnStatus.COMPLETED, final_text="answer")
        for event_type in (
            GatewayEventType.TURN_ACCEPTED,
            GatewayEventType.MESSAGE_DELTA,
            GatewayEventType.MESSAGE_COMPLETED,
            GatewayEventType.TURN_COMPLETED,
        ):
            repository.append_event(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                event_type=event_type,
            )

    active, _ = repository.create_turn(
        turn_id="active",
        session_id="session-1",
        workspace_id="workspace-1",
        user_id="alice",
        input_text="running",
        idempotency_key=None,
    )
    repository.update_turn(active.turn_id, TurnStatus.RUNNING)
    for event_type in (GatewayEventType.TURN_STARTED, GatewayEventType.MESSAGE_DELTA):
        repository.append_event(
            turn_id=active.turn_id,
            session_id=active.session_id,
            event_type=event_type,
        )

    stats = repository.prune_events(
        retention_days=7,
        max_events_per_session=3,
        now=datetime.now(timezone.utc) + timedelta(days=8),
    )

    assert stats == {"compacted": 4, "capped": 1, "remaining": 5}
    assert [event.type for event in repository.events_after(active.turn_id)] == [
        GatewayEventType.TURN_STARTED,
        GatewayEventType.MESSAGE_DELTA,
    ]
    terminal_events = sum(
        len(repository.events_after(turn_id)) for turn_id in terminal_ids
    )
    assert terminal_events == 3
    repository.close()
