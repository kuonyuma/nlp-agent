from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.application.turn_reliability import LostTurnClaimError, TurnReliabilityService, utc_now
from server.infrastructure.mysql.models import TurnModel


@pytest.mark.asyncio
async def test_claim_increments_generation_and_heartbeat_requires_the_same_owner() -> None:
    turn = TurnModel(id="turn-1", conversation_id="conversation-1", workspace_id="workspace-1", user_id="user-1", input_text="hi", status="accepted", claim_generation=0)
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.side_effect = [turn, turn, turn]
    service = TurnReliabilityService()

    generation = await service.claim_turn(session, turn_id="turn-1", worker_id="worker-a", lease_s=30)
    assert generation == 1
    await service.heartbeat(session, turn_id="turn-1", generation=1, worker_id="worker-a", lease_s=30)

    with pytest.raises(LostTurnClaimError):
        await service.heartbeat(session, turn_id="turn-1", generation=0, worker_id="worker-a", lease_s=30)


@pytest.mark.asyncio
async def test_recovery_invalidates_old_generation_and_emits_handover_without_resetting_sequence() -> None:
    turn = TurnModel(id="turn-1", conversation_id="conversation-1", workspace_id="workspace-1", user_id="user-1", input_text="hi", status="running", claim_generation=2, lease_expires_at=utc_now() - timedelta(seconds=1))
    session = AsyncMock()
    session.add = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [turn]
    latest_sequence = MagicMock()
    latest_sequence.first.return_value = 7
    session.scalars.side_effect = [scalars, latest_sequence]
    service = TurnReliabilityService()

    recovered = await service.recover_stuck_turns(session)

    assert recovered == ["turn-1"]
    assert turn.claim_generation == 3
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(getattr(item, "event_type", None) == "turn.handover" and getattr(item, "sequence", None) == 8 for item in added)


@pytest.mark.asyncio
async def test_operation_replay_uses_stable_turn_operation_identity() -> None:
    operation = AsyncMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = operation

    restored = await TurnReliabilityService().record_operation(session, turn_id="turn-1", generation=2, operation_id="tool-1", tool_name="send_message", request={})

    assert restored is operation
    session.add.assert_not_called()
