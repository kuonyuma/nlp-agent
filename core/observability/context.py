"""Trace correlation propagated explicitly at boundaries and implicitly in-process."""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator

from pydantic import BaseModel, ConfigDict


class TelemetryContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    span_id: str
    session_id: str
    turn_id: str
    workspace_id: str = "default"
    user_id: str = "default"
    channel: str = "cli"
    worker_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        turn_id: str,
        workspace_id: str = "default",
        user_id: str = "default",
        channel: str = "cli",
        request_id: str | None = None,
    ) -> "TelemetryContext":
        return cls(
            request_id=request_id or uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
            span_id=uuid.uuid4().hex,
            session_id=session_id,
            turn_id=turn_id,
            workspace_id=workspace_id,
            user_id=user_id,
            channel=channel,
        )

    def child(self, *, span_id: str | None = None, worker_id: str | None = None) -> "TelemetryContext":
        return self.model_copy(
            update={
                "span_id": span_id or uuid.uuid4().hex,
                "worker_id": worker_id if worker_id is not None else self.worker_id,
            }
        )

    def configurable(self) -> dict[str, str]:
        values = self.model_dump(exclude_none=True)
        return {f"telemetry_{key}": str(value) for key, value in values.items()}

    @classmethod
    def from_config(cls, config: dict | None) -> "TelemetryContext | None":
        configurable = (config or {}).get("configurable", {})
        values = {
            key.removeprefix("telemetry_"): value
            for key, value in configurable.items()
            if key.startswith("telemetry_")
        }
        required = {"request_id", "trace_id", "span_id", "session_id", "turn_id"}
        return cls.model_validate(values) if required.issubset(values) else None


_CURRENT: contextvars.ContextVar[TelemetryContext | None] = contextvars.ContextVar(
    "nlp_telemetry_context", default=None
)


def current_telemetry_context() -> TelemetryContext | None:
    return _CURRENT.get()


@contextmanager
def bind_telemetry_context(context: TelemetryContext) -> Iterator[TelemetryContext]:
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
