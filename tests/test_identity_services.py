import pytest

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.session_context import SessionContext
from server.agent.session_service import LocalSessionService


@pytest.mark.asyncio
async def test_session_service_filters_and_rejects_foreign_owner(monkeypatch):
    index = {
        "active_session": None,
        "sessions": {
            "session_alice": {
                "user_id": "alice",
                "workspace_id": "w1",
                "channel": "web",
                "created_at": 1,
                "last_active": 1,
            },
            "session_bob": {
                "user_id": "bob",
                "workspace_id": "w1",
                "channel": "web",
                "created_at": 2,
                "last_active": 2,
            },
        },
    }
    monkeypatch.setattr(
        "server.agent.session_service._load_sessions_index", lambda: index
    )
    service = LocalSessionService()
    alice = AuthenticatedPrincipal(
        user_id="alice", workspace_ids=frozenset({"w1"}), roles=frozenset({"student"})
    )

    sessions = await service.list(alice)
    assert [item["session_id"] for item in sessions] == ["session_alice"]
    with pytest.raises(AccessDeniedError):
        await service.resolve(alice, "session_bob")
