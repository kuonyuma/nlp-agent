"""Typed protocol shared by Coordinator and isolated Worker runtimes."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal


WorkerCommandKind = Literal["continue", "cancel", "reprioritize"]
WorkerWaitMode = Literal["all", "any", "quorum"]


@dataclass(frozen=True, slots=True)
class WorkerCommand:
    command_id: str
    session_id: str
    worker_id: str
    kind: WorkerCommandKind
    content: str
    created_at: float

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        worker_id: str,
        kind: WorkerCommandKind,
        content: str,
    ) -> "WorkerCommand":
        return cls(
            command_id=str(uuid.uuid4()),
            session_id=session_id,
            worker_id=worker_id,
            kind=kind,
            content=content,
            created_at=time.time(),
        )


@dataclass(frozen=True, slots=True)
class WorkerWaitPlan:
    session_id: str
    parent_turn_id: str
    worker_ids: frozenset[str]
    mode: WorkerWaitMode
    quorum: int
    timeout_s: float
