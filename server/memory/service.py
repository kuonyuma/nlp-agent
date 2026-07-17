"""WebUI/API-safe façade for scoped memory inspection and explicit edits."""

from __future__ import annotations

from typing import Any

from core.session_context import SessionContext
from core.identity import AuthenticatedPrincipal
from server.memory.runtime import MemoryRuntime, global_memory_runtime
from server.memory.types import MemoryScopeKind


class LocalMemoryService:
    def __init__(self, runtime: MemoryRuntime = global_memory_runtime) -> None:
        self.runtime = runtime

    async def inspect(
        self, principal: AuthenticatedPrincipal, context: SessionContext
    ) -> dict[str, Any]:
        principal.require_context(context)
        manager = self.runtime.manager(context)
        return {
            "workspace_id": context.workspace_id,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "indexes": manager.load_memory_index(),
            "topics": manager.scan_memory_headers(),
            "recent_session_archives": [
                row.model_dump(mode="json")
                for row in manager.read_archives(session_id=context.session_id)[-20:]
            ],
            "curator_cursor": manager.get_curator_cursor(),
        }

    async def remember(
        self,
        principal: AuthenticatedPrincipal,
        context: SessionContext,
        *,
        filename: str,
        content: str,
        memory_type: str,
        description: str,
        scope: MemoryScopeKind,
    ) -> str:
        principal.require_context(context)
        return self.runtime.manager(context).save_memory_topic(
            filename,
            content,
            memory_type,
            description,
            scope=scope,
        )

    async def forget(
        self,
        principal: AuthenticatedPrincipal,
        context: SessionContext,
        *,
        filename: str,
        scope: MemoryScopeKind,
    ) -> None:
        principal.require_context(context)
        self.runtime.manager(context).delete_memory_topic(filename, scope=scope)

    async def curate(
        self, principal: AuthenticatedPrincipal, context: SessionContext
    ) -> int:
        principal.require_context(context)
        return await self.runtime.curate_now(context)


local_memory_service = LocalMemoryService()
