from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from server.teacher.analytics import analyze
from server.teacher.models import TeachingGoals, UpdateTeachingGoals


class TeacherService:
    @staticmethod
    def require_teacher(principal: AuthenticatedPrincipal, workspace_id: str) -> None:
        if not (principal.is_admin or "teacher" in principal.roles):
            raise AccessDeniedError("teacher role is required")
        principal.require_workspace(workspace_id)

    async def goals(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        settings = await gateway.get_user_settings(principal)
        key = f"teacher_goals:{workspace_id}"
        value = settings["settings"].get(key) or TeachingGoals(workspace_id=workspace_id).model_dump(mode="json")
        return {"goals": value, "revision": settings["revision"], "updated_at": settings["updated_at"]}

    async def update_goals(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, body: UpdateTeachingGoals) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        goals = TeachingGoals(workspace_id=workspace_id, **body.model_dump()).model_dump(mode="json")
        result = await gateway.update_user_settings(principal, {f"teacher_goals:{workspace_id}": goals})
        return {"goals": goals, "revision": result["revision"], "updated_at": result["updated_at"]}

    async def analytics(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, days: int = 30, limit: int = 2_000) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        rows = await asyncio.to_thread(gateway.repository.list_questions, workspace_id=workspace_id, since=since, limit=limit)
        return {"workspace_id": workspace_id, "period_days": days, **analyze(rows)}


teacher_service = TeacherService()
