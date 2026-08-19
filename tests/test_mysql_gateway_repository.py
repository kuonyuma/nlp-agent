from __future__ import annotations

from unittest.mock import MagicMock, patch, sentinel

import pytest

from core.learning import ExerciseState, LearningContext, LearningProgress
from gateway.contracts import TurnStatus
from gateway.mysql_repository import MySQLGatewayRepository


def test_record_parses_json_state_columns_returned_as_text() -> None:
    repository = object.__new__(MySQLGatewayRepository)
    record = repository._record(
        {
            "id": "turn-1",
            "conversation_id": "session_x",
            "workspace_id": "default",
            "user_id": "user-1",
            "status": "accepted",
            "input_text": "hello",
            "learning_state_json": (
                '{"context": {"mode": "practice"}, "progress": {"stage": "start"}, "exercise": null}'
            ),
            "created_at": "2026-08-05 00:00:00",
            "started_at": None,
            "completed_at": None,
        }
    )

    assert record.turn_id == "turn-1"
    assert record.status == TurnStatus.ACCEPTED
    assert record.learning_context == LearningContext(mode="practice")
    assert record.learning_progress == LearningProgress()
    assert record.exercise_state is None


def test_ensure_conversation_creates_and_verifies_the_parent_record() -> None:
    connection = MagicMock()
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    lookup = MagicMock()
    lookup.mappings.return_value.one.return_value = {
        "workspace_id": "default",
        "owner_user_id": "user-1",
    }
    connection.execute.side_effect = [empty, MagicMock(), lookup]

    MySQLGatewayRepository._ensure_conversation(
        connection,
        session_id="session_ecd63e64644e4df28801b77a49efe6e8",
        workspace_id="default",
        user_id="user-1",
        title="hello",
    )

    insert_call = connection.execute.call_args_list[1]
    assert "INSERT INTO nlp_conversations" in str(insert_call.args[0])
    assert insert_call.args[1] == {
        "id": "session_ecd63e64644e4df28801b77a49efe6e8",
        "workspace": "default",
        "user": "user-1",
        "title": "hello",
    }


def test_ensure_conversation_rejects_an_identity_collision() -> None:
    connection = MagicMock()
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    lookup = MagicMock()
    lookup.mappings.return_value.one.return_value = {
        "workspace_id": "other",
        "owner_user_id": "user-2",
    }
    connection.execute.side_effect = [empty, MagicMock(), lookup]

    with pytest.raises(PermissionError, match="conversation identity"):
        MySQLGatewayRepository._ensure_conversation(
            connection,
            session_id="session-shared",
            workspace_id="default",
            user_id="user-1",
            title="hello",
        )


def test_create_turn_ensures_the_conversation_before_inserting_the_turn() -> None:
    repository = object.__new__(MySQLGatewayRepository)
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    repository._engine = engine

    with (
        patch.object(MySQLGatewayRepository, "_ensure_conversation") as ensure,
        patch.object(MySQLGatewayRepository, "_row", return_value={"id": "turn-1"}),
        patch.object(MySQLGatewayRepository, "_record", return_value=sentinel.record),
    ):
        record, duplicate = repository.create_turn(
            turn_id="turn-1",
            session_id="session_ecd63e64644e4df28801b77a49efe6e8",
            workspace_id="default",
            user_id="user-1",
            input_text="hello",
            idempotency_key=None,
        )

    ensure.assert_called_once_with(
        connection,
        session_id="session_ecd63e64644e4df28801b77a49efe6e8",
        workspace_id="default",
        user_id="user-1",
        title="hello",
    )
    assert "INSERT INTO nlp_turns" in str(connection.execute.call_args.args[0])
    assert record is sentinel.record
    assert duplicate is False
