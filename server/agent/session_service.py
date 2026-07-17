"""Authenticated local session service used by the Backend Gateway."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.session_context import SessionContext, local_context_repository
from server.agent.session_storage import (
    CHAT_HISTORY_DIR,
    _load_sessions_index,
    _save_sessions_index,
    get_session_transcript_path,
)
from server.agent.node.session_storage import DATA_DIR


class LocalSessionService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def create(
        self,
        principal: AuthenticatedPrincipal,
        *,
        workspace_id: str = "default",
        channel: str = "web",
    ) -> SessionContext:
        principal.require_workspace(workspace_id)
        context = SessionContext.create(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            channel=channel,
        )
        async with self._lock:
            index = await asyncio.to_thread(_load_sessions_index)
            index.setdefault("sessions", {})[context.session_id] = {
                "created_at": time.time(),
                "last_active": time.time(),
                "user_id": context.user_id,
                "workspace_id": context.workspace_id,
                "channel": context.channel,
            }
            await asyncio.to_thread(_save_sessions_index, index)
        return context

    async def resolve(
        self, principal: AuthenticatedPrincipal, session_id: str
    ) -> SessionContext:
        SessionContext(session_id=session_id)
        async with self._lock:
            index = await asyncio.to_thread(_load_sessions_index)
            metadata = index.get("sessions", {}).get(session_id)
        if metadata is None:
            raise FileNotFoundError(f"session not found: {session_id}")
        context = SessionContext(
            session_id=session_id,
            user_id=str(metadata.get("user_id", "local")),
            workspace_id=str(metadata.get("workspace_id", "default")),
            channel=str(metadata.get("channel", "local")),
        )
        principal.require_context(context)
        return context

    async def list(self, principal: AuthenticatedPrincipal) -> list[dict[str, Any]]:
        async with self._lock:
            sessions = (await asyncio.to_thread(_load_sessions_index)).get("sessions", {})
        output = []
        for session_id, metadata in sessions.items():
            context = SessionContext(
                session_id=session_id,
                user_id=str(metadata.get("user_id", "local")),
                workspace_id=str(metadata.get("workspace_id", "default")),
                channel=str(metadata.get("channel", "local")),
            )
            if not principal.can_access(context):
                continue
            output.append({"session_id": session_id, **metadata})
        return sorted(output, key=lambda item: item.get("last_active", 0), reverse=True)

    async def messages(
        self, principal: AuthenticatedPrincipal, session_id: str
    ) -> list[dict[str, Any]]:
        await self.resolve(principal, session_id)
        path = Path(get_session_transcript_path(session_id))
        if not path.exists():
            return []

        def read() -> list[dict[str, Any]]:
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return rows

        return await asyncio.to_thread(read)

    async def touch(
        self, principal: AuthenticatedPrincipal, session_id: str
    ) -> SessionContext:
        context = await self.resolve(principal, session_id)
        async with self._lock:
            index = await asyncio.to_thread(_load_sessions_index)
            metadata = index.get("sessions", {}).get(session_id)
            if metadata is not None:
                metadata["last_active"] = time.time()
                await asyncio.to_thread(_save_sessions_index, index)
        return context

    async def delete(
        self, principal: AuthenticatedPrincipal, session_id: str
    ) -> SessionContext:
        context = await self.resolve(principal, session_id)
        async with self._lock:
            index = await asyncio.to_thread(_load_sessions_index)
            current = index.get("sessions", {}).get(session_id)
            if current is None:
                raise FileNotFoundError(session_id)
            stored = SessionContext(
                session_id=session_id,
                user_id=str(current.get("user_id", "local")),
                workspace_id=str(current.get("workspace_id", "default")),
                channel=str(current.get("channel", "local")),
            )
            if not principal.can_access(stored):
                raise AccessDeniedError(session_id)
            index["sessions"].pop(session_id, None)
            if index.get("active_session") == session_id:
                index["active_session"] = None
            await asyncio.to_thread(_save_sessions_index, index)

        def remove_local_data() -> None:
            transcript = Path(get_session_transcript_path(session_id))
            transcript.unlink(missing_ok=True)
            shutil.rmtree(Path(CHAT_HISTORY_DIR) / session_id, ignore_errors=True)
            shutil.rmtree(Path(DATA_DIR) / session_id, ignore_errors=True)
            local_context_repository.delete_session(context)

        await asyncio.to_thread(remove_local_data)
        from server.memory.runtime import global_memory_runtime

        await asyncio.to_thread(
            global_memory_runtime.manager(context).delete_session_archives,
            session_id,
        )
        return context


local_session_service = LocalSessionService()
