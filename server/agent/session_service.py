"""WebUI-facing local session API without a process-global active session."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from core.session_context import SessionContext
from server.agent.session_storage import (
    _load_sessions_index,
    _save_sessions_index,
    get_session_transcript_path,
)


class LocalSessionService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def create(self, **identity: str) -> SessionContext:
        context = SessionContext.create(**identity)
        async with self._lock:
            index = _load_sessions_index()
            index.setdefault("sessions", {})[context.session_id] = {
                "created_at": __import__("time").time(),
                "last_active": __import__("time").time(),
                "user_id": context.user_id,
                "workspace_id": context.workspace_id,
                "channel": context.channel,
            }
            _save_sessions_index(index)
        return context

    async def list(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            sessions = _load_sessions_index().get("sessions", {})
        output = []
        for session_id, metadata in sessions.items():
            if user_id is not None and metadata.get("user_id", "local") != user_id:
                continue
            output.append({"session_id": session_id, **metadata})
        return sorted(output, key=lambda item: item.get("last_active", 0), reverse=True)

    async def messages(self, context: SessionContext) -> list[dict[str, Any]]:
        path = Path(get_session_transcript_path(context.session_id))
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    async def delete(self, context: SessionContext) -> bool:
        async with self._lock:
            index = _load_sessions_index()
            existed = index.get("sessions", {}).pop(context.session_id, None) is not None
            if index.get("active_session") == context.session_id:
                index["active_session"] = None
            _save_sessions_index(index)
        path = get_session_transcript_path(context.session_id)
        if os.path.exists(path):
            os.remove(path)
        return existed


local_session_service = LocalSessionService()
