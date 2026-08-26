from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_manager_command_store_round_trips_pool_target() -> None:
    from server.sandbox.commands import RedisSandboxManagerCommandStore

    class FakeRedis:
        def __init__(self) -> None:
            self.rows: list[tuple[str, dict[str, str]]] = []
            self.values: dict[str, str] = {}

        async def xadd(self, _stream: str, fields: dict[str, str], **_kwargs: object) -> str:
            identifier = f"0-{len(self.rows) + 1}"
            self.rows.append((identifier, fields))
            return identifier

        async def xread(self, _streams: dict[str, str], **_kwargs: object):
            return [("nova:sandbox:manager:commands", self.rows)]

        async def get(self, key: str):
            return self.values.get(key)

        async def set(self, key: str, value: str, **kwargs: object):
            if kwargs.get("nx") and key in self.values:
                return False
            self.values[key] = value
            return True

    store = RedisSandboxManagerCommandStore(FakeRedis())
    command_id = await store.request_pool_target(
        profile_id="python-base", target=4, reason="class-start"
    )
    cursor, commands = await store.read()
    assert command_id == "0-1"
    assert cursor == "0-1"
    assert commands[0]["target"] == "4"
    assert commands[0]["reason"] == "class-start"
    assert float(commands[0]["expires_at"]) > time.time()
    assert await store.load_cursor() == "0-0"
    await store.save_cursor("0-1")
    assert await store.load_cursor() == "0-1"
    assert await store.mark_handled("0-1") is True
    assert await store.mark_handled("0-1") is False


def test_manager_command_expiry_fails_closed() -> None:
    from server.sandbox.commands import command_expired

    assert command_expired({}) is True
    assert command_expired({"expires_at": "not-a-timestamp"}) is True
    assert command_expired({"expires_at": "1"}, now=2) is True
    assert command_expired({"expires_at": "3"}, now=2) is False
