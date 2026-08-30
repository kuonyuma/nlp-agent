"""Production lifecycle for releasing abandoned quota Reservations."""

from __future__ import annotations

import asyncio
from typing import Any

from utils.logger import get_logger


logger = get_logger("nlp_agent.quota.reaper")


class QuotaReservationReaper:
    """Run the database-backed Reservation expiry sweep for a process."""

    def __init__(self, quota_service: Any, *, interval_seconds: float = 30.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._quota_service = quota_service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(),
                name="quota-reservation-reaper",
            )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._quota_service.expire_reservations)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("quota reservation expiry pass failed")
            await asyncio.sleep(self._interval_seconds)
