"""Risk grants and privacy-preserving local audit events for tool execution."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolRiskGrant(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    tool_name: str
    granted_by: str
    reason: str = ""
    expires_at: float

    @property
    def active(self) -> bool:
        return self.expires_at > time.time()


class ToolAuthorizationManager:
    def __init__(self) -> None:
        self._grants: dict[tuple[str, str], ToolRiskGrant] = {}
        self._lock = threading.RLock()

    def grant(
        self,
        *,
        session_id: str,
        tool_name: str,
        granted_by: str,
        reason: str = "",
        ttl_s: float = 300,
    ) -> ToolRiskGrant:
        if not session_id:
            raise ValueError("high-risk grants require session_id")
        if not granted_by:
            raise ValueError("high-risk grants require granted_by")
        if not reason.strip():
            raise ValueError("high-risk grants require an explicit reason")
        if ttl_s <= 0 or ttl_s > 86_400:
            raise ValueError("high-risk grant ttl_s must be in (0, 86400]")
        grant = ToolRiskGrant(
            session_id=session_id,
            tool_name=tool_name,
            granted_by=granted_by,
            reason=reason,
            expires_at=time.time() + ttl_s,
        )
        with self._lock:
            self._grants[(session_id, tool_name)] = grant
        return grant

    def is_granted(self, session_id: str, tool_name: str) -> bool:
        with self._lock:
            grant = self._grants.get((session_id, tool_name))
            if grant is None:
                return False
            if not grant.active:
                self._grants.pop((session_id, tool_name), None)
                return False
            return True

    def revoke(self, session_id: str, tool_name: str) -> bool:
        with self._lock:
            return self._grants.pop((session_id, tool_name), None) is not None

    def revoke_session(self, session_id: str) -> int:
        with self._lock:
            keys = [key for key in self._grants if key[0] == session_id]
            for key in keys:
                self._grants.pop(key, None)
            return len(keys)


class ToolAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    session_id: str = ""
    role: str = ""
    profile: str = ""
    tool_name: str
    provider: str = ""
    phase: Literal["denied", "attempt", "retry", "completed"]
    attempt: int = Field(default=1, ge=0)
    outcome: Literal["started", "success", "error", "denied"]
    error_kind: str = ""
    duration_ms: int = Field(default=0, ge=0)
    argument_keys: tuple[str, ...] = ()


class ToolAuditLog:
    """Bounded in-memory query plus append-only per-session JSONL audit."""

    def __init__(self, root: Path | None = None, memory_limit: int = 2_000) -> None:
        project = Path(__file__).resolve().parent.parent
        self.root = root or project / ".data" / "tool-audit"
        self.root.mkdir(parents=True, exist_ok=True)
        self._events: deque[ToolAuditEvent] = deque(maxlen=memory_limit)
        self._memory_lock = threading.Lock()
        self._file_lock = threading.Lock()

    async def emit(self, event: ToolAuditEvent) -> None:
        with self._memory_lock:
            self._events.append(event)
        await asyncio.to_thread(self._append, event)

    def recent(
        self, *, session_id: str | None = None, limit: int = 100
    ) -> tuple[ToolAuditEvent, ...]:
        with self._memory_lock:
            events = list(self._events)
        if session_id is not None:
            events = [item for item in events if item.session_id == session_id]
        return tuple(events[-max(0, limit) :])

    def _append(self, event: ToolAuditEvent) -> None:
        identity = event.session_id or "system"
        stem = base64.urlsafe_b64encode(identity.encode()).decode().rstrip("=")
        path = self.root / f"{stem}.jsonl"
        with self._file_lock, path.open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json() + "\n")


global_tool_authorizations = ToolAuthorizationManager()
global_tool_audit_log = ToolAuditLog()
