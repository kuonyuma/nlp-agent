"""Redis command queue between the Web control plane and isolated Manager."""

from __future__ import annotations

from typing import Any

from configs.settings import settings
from .faults import SandboxFaultInjector


class RedisSandboxManagerCommandStore:
    def __init__(
        self,
        client: Any,
        *,
        stream: str = "nova:sandbox:manager:commands",
        fault_injector: SandboxFaultInjector | None = None,
    ) -> None:
        self._client = client
        self._stream = stream
        self._faults = fault_injector or SandboxFaultInjector.from_env()

    async def request_pool_target(
        self,
        *,
        profile_id: str,
        target: int,
        reason: str,
        execute_at: str | None = None,
    ) -> str:
        self._faults.fail_if_configured("redis.xadd")
        command_id = await self._client.xadd(
            self._stream,
            {
                "type": "pool_target",
                "profile_id": profile_id,
                "target": str(target),
                "reason": reason,
                "execute_at": execute_at or "",
            },
            maxlen=1_000,
            approximate=True,
        )
        return command_id.decode("utf-8") if isinstance(command_id, bytes) else str(command_id)

    async def read(
        self,
        *,
        after_id: str = "0-0",
        count: int = 20,
        block_ms: int = 1000,
    ) -> tuple[str, list[dict[str, str]]]:
        self._faults.fail_if_configured("redis.xread")
        rows = await self._client.xread({self._stream: after_id}, count=count, block=max(1, block_ms))
        if not rows:
            return after_id, []
        commands: list[dict[str, str]] = []
        latest = after_id
        for _stream, messages in rows:
            for message_id, fields in messages:
                latest = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
                parsed = {
                    (key.decode("utf-8") if isinstance(key, bytes) else str(key)):
                    (value.decode("utf-8") if isinstance(value, bytes) else str(value))
                    for key, value in fields.items()
                }
                parsed["id"] = latest
                commands.append(parsed)
        return latest, commands

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def create_sandbox_manager_command_store() -> RedisSandboxManagerCommandStore | None:
    redis_url = settings.NLP_AGENT_REDIS_URL.strip()
    if not redis_url:
        return None
    from redis.asyncio import Redis

    return RedisSandboxManagerCommandStore(Redis.from_url(redis_url, decode_responses=True))
