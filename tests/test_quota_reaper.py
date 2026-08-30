import asyncio

import pytest

from server.quota.reaper import QuotaReservationReaper


@pytest.mark.asyncio
async def test_reaper_runs_expiry_and_stops_cleanly():
    class Service:
        def __init__(self) -> None:
            self.calls = 0

        def expire_reservations(self) -> int:
            self.calls += 1
            return 1

    service = Service()
    reaper = QuotaReservationReaper(service, interval_seconds=0.01)
    reaper.start()
    await asyncio.sleep(0.06)
    await reaper.stop()

    assert service.calls >= 1
    assert reaper.task is None
