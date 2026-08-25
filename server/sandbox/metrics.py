"""Durable, bounded capacity samples for the developer sandbox dashboard."""

from __future__ import annotations

import json
import time
from typing import Any

from configs.settings import settings


class RedisSandboxMetricsStore:
    def __init__(self, client: Any, *, key: str = "nova:sandbox:metrics:capacity", retention_seconds: int = 7 * 24 * 3600, max_samples: int = 2_000) -> None:
        self._client = client
        self._key = key
        self._retention_seconds = max(60, retention_seconds)
        self._max_samples = max(100, max_samples)

    async def record(self, sample: dict[str, object]) -> list[dict[str, object]]:
        timestamp = float(sample.get("timestamp", time.time()))
        member = json.dumps(sample, separators=(",", ":"), sort_keys=True)
        await self._client.zadd(self._key, {member: timestamp})
        await self._client.zremrangebyscore(self._key, 0, timestamp - self._retention_seconds)
        trim = getattr(self._client, "zremrangebyrank", None)
        card = getattr(self._client, "zcard", None)
        if trim is not None and card is not None:
            count = int(await card(self._key))
            if count > self._max_samples:
                # Redis rank endpoints are inclusive.  Remove precisely the
                # oldest excess rows; using a negative end rank can delete the
                # entire sorted set when it is smaller than max_samples.
                await trim(self._key, 0, count - self._max_samples - 1)
        await self._client.expire(self._key, self._retention_seconds)
        rows = await self._client.zrange(self._key, -min(self._max_samples, 60), -1)
        samples: list[dict[str, object]] = []
        for row in rows:
            try:
                value = row.decode("utf-8") if isinstance(row, bytes) else row
                parsed = json.loads(value)
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                samples.append(parsed)
        return samples

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def create_sandbox_metrics_store() -> RedisSandboxMetricsStore | None:
    redis_url = settings.NLP_AGENT_REDIS_URL.strip()
    if not redis_url:
        return None
    from redis.asyncio import Redis

    return RedisSandboxMetricsStore(
        Redis.from_url(redis_url, decode_responses=True),
        retention_seconds=settings.NLP_AGENT_SANDBOX_METRICS_RETENTION_S,
    )


default_sandbox_metrics_store = create_sandbox_metrics_store()
