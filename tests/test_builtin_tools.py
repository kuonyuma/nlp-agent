import datetime
import json

import pytest

from server.tools.api import time_tool


@pytest.mark.asyncio
async def test_current_time_is_computed_in_declared_shanghai_timezone(monkeypatch):
    real_datetime = datetime.datetime

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is not None
            return real_datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz)

    monkeypatch.setattr(time_tool.datetime, "datetime", FixedDateTime)

    payload = json.loads(await time_tool.get_current_time.ainvoke({}))

    assert payload["datetime"] == "2026-01-02 03:04:05"
    assert payload["timezone"] == "Asia/Shanghai"
