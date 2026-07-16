"""Framework-neutral query boundary for a future Gateway or WebUI."""

from __future__ import annotations

import asyncio
from typing import Any

from core.observability.runtime import TelemetryRuntime, global_telemetry


class ObservabilityService:
    """Read-only facade; HTTP/WebSocket adapters should depend only on this class."""

    def __init__(self, runtime: TelemetryRuntime = global_telemetry) -> None:
        self.runtime = runtime

    async def overview(self, days: int = 30) -> dict[str, Any]:
        result = await asyncio.to_thread(self.runtime.repository.overview, days)
        return {**result, "runtime": self.runtime.health()}

    async def traces(self, *, limit: int = 100, session_id: str | None = None,
                     status: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.runtime.repository.list_traces,
            limit=limit, session_id=session_id, status=status,
        )

    async def trace(self, trace_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.runtime.repository.trace_detail, trace_id)

    async def usage(self, days: int = 30) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.runtime.repository.usage, days)

    async def sessions(self, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.runtime.repository.sessions, days, limit)

    async def events(self, *, limit: int = 200, level: str | None = None,
                     trace_id: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.runtime.repository.recent_events,
            limit=limit, level=level, trace_id=trace_id,
        )

    async def errors(self, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.runtime.repository.errors, days, limit)

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.runtime.health)

    def subscribe(self, maxsize: int = 500) -> asyncio.Queue[dict[str, Any]]:
        """Return a bounded live-event queue suitable for a future WebSocket adapter."""
        return self.runtime.subscribe(maxsize=maxsize)

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.runtime.unsubscribe(queue)


global_observability_service = ObservabilityService()
