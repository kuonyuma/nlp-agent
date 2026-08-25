"""Durable, bounded capacity samples for the developer sandbox dashboard."""

from __future__ import annotations

import json
import time
from typing import Any

from configs.settings import settings
from .faults import SandboxFaultInjector


class RedisSandboxMetricsStore:
    def __init__(
        self,
        client: Any,
        *,
        key: str = "nova:sandbox:metrics:capacity",
        retention_seconds: int = 7 * 24 * 3600,
        max_samples: int = 2_000,
        fault_injector: SandboxFaultInjector | None = None,
    ) -> None:
        self._client = client
        self._key = key
        self._retention_seconds = max(60, retention_seconds)
        self._max_samples = max(100, max_samples)
        self._faults = fault_injector or SandboxFaultInjector.from_env()

    async def record(self, sample: dict[str, object]) -> list[dict[str, object]]:
        self._faults.fail_if_configured("redis.metrics")
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

    async def latest(self) -> dict[str, object] | None:
        """Read the most recent bounded sample for Manager feedback."""
        self._faults.fail_if_configured("redis.metrics.read")
        rows = await self._client.zrange(self._key, -1, -1)
        if not rows:
            return None
        raw = rows[-1]
        try:
            value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            parsed = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


class RedisSandboxAdaptiveStateStore:
    """Persist adaptive target/cooldown state outside the Web process."""

    def __init__(self, client: Any, *, key: str = "nova:sandbox:capacity:adaptive", fault_injector: SandboxFaultInjector | None = None) -> None:
        self._client = client
        self._key = key
        self._faults = fault_injector or SandboxFaultInjector.from_env()

    async def load(self) -> tuple[int | None, float | None]:
        self._faults.fail_if_configured("redis.state.read")
        values = await self._client.hgetall(self._key)
        if not values:
            return None, None
        def value(name: str) -> str | None:
            raw = values.get(name) if isinstance(values, dict) else None
            if isinstance(raw, bytes):
                return raw.decode("utf-8")
            return str(raw) if raw is not None else None
        target = value("target")
        scaled_at = value("scaled_at")
        try:
            parsed_target = int(target) if target is not None else None
        except ValueError:
            parsed_target = None
        try:
            parsed_scaled_at = float(scaled_at) if scaled_at is not None else None
        except ValueError:
            parsed_scaled_at = None
        return parsed_target, parsed_scaled_at

    async def save(self, *, target: int, scaled_at: float) -> None:
        self._faults.fail_if_configured("redis.state.write")
        await self._client.hset(self._key, mapping={"target": target, "scaled_at": scaled_at})

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def create_sandbox_adaptive_state_store() -> RedisSandboxAdaptiveStateStore | None:
    redis_url = settings.NLP_AGENT_REDIS_URL.strip()
    if not redis_url:
        return None
    from redis.asyncio import Redis

    return RedisSandboxAdaptiveStateStore(Redis.from_url(redis_url, decode_responses=True))


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
