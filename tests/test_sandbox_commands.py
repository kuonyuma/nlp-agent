from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_manager_command_store_round_trips_pool_target() -> None:
    from server.sandbox.commands import RedisSandboxManagerCommandStore

    class FakeRedis:
        def __init__(self) -> None:
            self.rows: list[tuple[str, dict[str, str]]] = []

        async def xadd(self, _stream: str, fields: dict[str, str], **_kwargs: object) -> str:
            identifier = f"0-{len(self.rows) + 1}"
            self.rows.append((identifier, fields))
            return identifier

        async def xread(self, _streams: dict[str, str], **_kwargs: object):
            return [("nova:sandbox:manager:commands", self.rows)]

    store = RedisSandboxManagerCommandStore(FakeRedis())
    command_id = await store.request_pool_target(
        profile_id="python-base", target=4, reason="class-start"
    )
    cursor, commands = await store.read()
    assert command_id == "0-1"
    assert cursor == "0-1"
    assert commands[0]["target"] == "4"
    assert commands[0]["reason"] == "class-start"
