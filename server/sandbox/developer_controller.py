from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.rbac import Permission, authorization_service
from server.auth.dependencies import Principal, get_db_session
from server.infrastructure.mysql.models import SandboxRuntimeInstanceModel

from .developer import summarize_runtime_states

router = APIRouter(prefix="/api/v1/developer/sandbox", tags=["developer-sandbox"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/overview")
async def sandbox_overview(db: DbSession, principal: Principal) -> dict[str, object]:
    authorization_service.require(principal, Permission.SYSTEM_RUNTIME_MONITOR)
    rows = (await db.execute(select(SandboxRuntimeInstanceModel.state, func.count()).group_by(SandboxRuntimeInstanceModel.state))).all()
    return {"runtime_states": summarize_runtime_states([(str(state), int(count)) for state, count in rows])}
