"""Versioned framework-neutral contracts for the Backend Gateway Core."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TurnStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class GatewayEventType(str, Enum):
    TURN_ACCEPTED = "turn.accepted"
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_CANCELLED = "turn.cancelled"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    MESSAGE_INJECTED = "message.injected"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    WORKER_UPDATE = "worker.update"
    GAP = "stream.gap"


class SubmitTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    content: str = Field(min_length=1, max_length=200_000)
    idempotency_key: str | None = Field(default=None, max_length=128)


class InjectMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    content: str = Field(min_length=1, max_length=200_000)


class TurnAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    session_id: str
    status: TurnStatus
    duplicate: bool = False


class TurnRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    session_id: str
    workspace_id: str
    user_id: str
    status: TurnStatus
    input_text: str
    final_text: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GatewayEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    turn_id: str
    session_id: str
    sequence: int = Field(ge=1)
    type: GatewayEventType
    created_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class GatewayHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    started: bool
    accepting_turns: bool
    active_turns: int
    subscribers: int
    database: str
    durable_events: int


class GatewayNotStartedError(RuntimeError):
    pass


class TurnConflictError(RuntimeError):
    pass


class ResourceNotFoundError(LookupError):
    pass
