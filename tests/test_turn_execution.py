import pytest

from core.learning import TeachingMaterials
from core.session_context import SessionContext
from gateway.contracts import GatewayEventType, TurnStatus
from gateway.dispatch import TurnTask
from gateway.turn_execution import InProcessTurnExecutor


class SuccessfulEngine:
    async def run_turn(self, _context, _turn_id, _content):
        return 'answer<!-- guided-result: {"status":"completed"} -->'

    async def cancel_turn(self, _context, _turn_id):
        return None


class FailingLearningRepository:
    def __init__(self):
        self.statuses = []

    def update_turn(self, _turn_id, status, **_changes):
        self.statuses.append(status)

    def advance_guided_session(self, _guided_session_id, **_changes):
        raise RuntimeError("learning store unavailable")


@pytest.mark.asyncio
async def test_learning_finalization_failure_moves_running_turn_to_failed():
    repository = FailingLearningRepository()
    events = []

    async def emit(_turn_id, _session_id, event_type, payload):
        events.append((event_type, payload))

    executor = InProcessTurnExecutor(SuccessfulEngine(), repository, emit)
    task = TurnTask(
        context=SessionContext(session_id="session-1"),
        turn_id="turn-1",
        content="hello",
        learning_context=None,
        learning_progress=None,
        exercise_state=None,
        teaching_materials=TeachingMaterials(),
        guided_session_id="guided-1",
        exercise_session_id=None,
    )

    await executor.run(task)

    assert repository.statuses == [TurnStatus.RUNNING, TurnStatus.FAILED]
    assert [event_type for event_type, _payload in events] == [
        GatewayEventType.TURN_STARTED,
        GatewayEventType.TURN_FAILED,
    ]
    assert events[-1][1]["error_kind"] == "RuntimeError"
