from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.rbac import Permission, authorization_service
from server.auth.dependencies import Principal, get_db_session
from configs.settings import settings
from server.infrastructure.mysql.models import SandboxExecutionModel, SandboxRuntimeInstanceModel
from server.rbac.service import rbac_service

from .developer import capacity_snapshot, summarize_execution_latency, summarize_runtime_states
from .events import default_sandbox_event_store
from .metrics import default_sandbox_metrics_store

router = APIRouter(prefix="/api/v1/developer/sandbox", tags=["developer-sandbox"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _require_monitor(principal: Principal) -> None:
    authorization_service.require(principal, Permission.SYSTEM_RUNTIME_MONITOR)


@router.get("/overview")
async def sandbox_overview(db: DbSession, principal: Principal) -> dict[str, object]:
    _require_monitor(principal)
    rows = (await db.execute(select(SandboxRuntimeInstanceModel.state, func.count()).group_by(SandboxRuntimeInstanceModel.state))).all()
    runtime_states = summarize_runtime_states([(str(state), int(count)) for state, count in rows])
    execution_rows = (await db.execute(
        select(SandboxExecutionModel.started_at, SandboxExecutionModel.completed_at)
        .where(SandboxExecutionModel.started_at.is_not(None), SandboxExecutionModel.completed_at.is_not(None))
        .order_by(SandboxExecutionModel.created_at.desc()).limit(1000)
    )).all()
    durations: list[float] = []
    for started_at, completed_at in execution_rows:
        if started_at is None or completed_at is None:
            continue
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        duration = (completed_at - started_at).total_seconds() * 1000
        if duration >= 0:
            durations.append(duration)
    capacity = capacity_snapshot(runtime_states, target=settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_TARGET)
    alerts: list[dict[str, str]] = []
    if capacity["deficit"] > 0:
        alerts.append({"code": "pool_deficit", "severity": "warning", "message": "Warm Pool ready capacity is below target."})
    if runtime_states["failed"] > 0:
        alerts.append({"code": "runtime_failed", "severity": "critical", "message": "Sandbox runtimes require reconciliation."})
    sample = {
        "timestamp": datetime.now(UTC).timestamp(),
        "ready": capacity["ready"], "creating": capacity["creating"],
        "target": capacity["target"], "deficit": capacity["deficit"],
    }
    history = [sample]
    if default_sandbox_metrics_store is not None:
        try:
            history = await default_sandbox_metrics_store.record(sample)
        except Exception:
            history = [sample]
    return {
        "runtime_states": runtime_states,
        "capacity": capacity,
        "execution_latency": summarize_execution_latency(durations),
        "alerts": alerts,
        "capacity_history": history,
        "sampled_at": datetime.now(UTC).isoformat(),
    }


@router.get("/runtimes")
async def list_sandbox_runtimes(db: DbSession, principal: Principal) -> dict[str, list[dict[str, object | None]]]:
    _require_monitor(principal)
    rows = (await db.execute(
        select(SandboxRuntimeInstanceModel).order_by(SandboxRuntimeInstanceModel.updated_at.desc()).limit(200)
    )).scalars().all()
    return {"items": [
        {
            "id": str(row.id), "state": row.state, "node_id": row.node_id,
            "runtime_kind": row.runtime_kind, "resource_profile_id": row.resource_profile_id,
            "external_runtime_id": row.external_runtime_id, "failure_reason": row.failure_reason,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]}


@router.post("/runtimes/{runtime_id}/drain")
async def drain_sandbox_runtime(runtime_id: str, db: DbSession, principal: Principal) -> dict[str, str]:
    _require_monitor(principal)
    runtime = await db.get(SandboxRuntimeInstanceModel, runtime_id, with_for_update=True)
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox runtime not found.")
    if runtime.state not in {"assigned", "ready_unbound", "claiming"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Runtime is already {runtime.state}.")
    runtime.state = "draining"
    runtime.failure_reason = "developer.drain_requested"
    await rbac_service.audit(
        db, actor_user_id=principal.user_id, target_user_id=None, decision="allow",
        reason_code="sandbox_runtime_drain_requested", permission_code=Permission.SYSTEM_RUNTIME_MONITOR.value,
        resource_type="sandbox_runtime", resource_id=runtime_id,
    )
    await db.commit()
    return {"id": runtime_id, "state": runtime.state}


@router.get("/runtimes/{runtime_id}")
async def get_sandbox_runtime(runtime_id: str, db: DbSession, principal: Principal) -> dict[str, object | None]:
    _require_monitor(principal)
    runtime = await db.get(SandboxRuntimeInstanceModel, runtime_id)
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox runtime not found.")
    return {
        "id": str(runtime.id), "state": runtime.state, "node_id": runtime.node_id,
        "runtime_kind": runtime.runtime_kind, "resource_profile_id": runtime.resource_profile_id,
        "external_runtime_id": runtime.external_runtime_id, "image_digest": runtime.image_digest,
        "environment_id": str(runtime.environment_id) if runtime.environment_id else None,
        "generation": runtime.generation, "last_heartbeat_at": runtime.last_heartbeat_at.isoformat() if runtime.last_heartbeat_at else None,
        "failure_reason": runtime.failure_reason, "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else None,
    }


@router.get("/executions")
async def list_sandbox_executions(db: DbSession, principal: Principal) -> dict[str, list[dict[str, object | None]]]:
    _require_monitor(principal)
    rows = (await db.execute(select(SandboxExecutionModel).order_by(SandboxExecutionModel.created_at.desc()).limit(200))).scalars().all()
    return {"items": [
        {
            "id": str(row.id), "owner_user_id": str(row.owner_user_id), "environment_id": str(row.environment_id),
            "runtime_instance_id": str(row.runtime_instance_id) if row.runtime_instance_id else None,
            "status": row.status, "generation": row.generation, "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None, "exit_reason": row.exit_reason,
        }
        for row in rows
    ]}


@router.get("/executions/{execution_id}/events")
async def replay_sandbox_execution_events(
    execution_id: str,
    db: DbSession,
    principal: Principal,
    after_event_id: str | None = None,
) -> dict[str, object]:
    _require_monitor(principal)
    execution = await db.get(SandboxExecutionModel, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox execution not found.")
    events = await default_sandbox_event_store.replay(
        execution_id, user_id=str(execution.owner_user_id), after_event_id=after_event_id,
    )
    return {"execution_id": execution_id, "events": events}
