"""Model-facing Sandbox tools for the Phase 4 closed loop.

The model receives a deliberately small control surface.  Scratch execution is
always isolated from the user's Interactive Kernel; active-kernel execution and
reset are high-risk tools and still require the normal ToolRuntime grant plus an
explicit ``confirmed`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from configs.settings import settings
from server.infrastructure.mysql.models import (
    SandboxEnvironmentModel,
    SandboxExecutionModel,
    SandboxLeaseModel,
    SandboxRuntimeInstanceModel,
    SessionModel,
    UserModel,
)

from .contracts import SandboxScope
from .events import default_sandbox_event_store
from .inmemory_runtime import InMemoryRuntime
from .manager import WarmPoolManager
from .optimization import AdaptivePoolPolicy
from .ticket import SandboxTicketClaims, SandboxTicketSigner


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _error(code: str, message: str, **details: object) -> dict[str, object]:
    return {"ok": False, "code": code, "error": message, "details": details}


@dataclass(frozen=True)
class _AuthorizedModelContext:
    context: Any
    scope: SandboxScope | None
    environment_id: str | None
    lease_id: str | None
    runtime_id: str | None


class SandboxModelToolService:
    """Resolve model calls against the authenticated Sandbox boundary."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        manager: WarmPoolManager | None = None,
        interactive: InMemoryRuntime | None = None,
    ) -> None:
        self.mode = (mode or settings.NLP_AGENT_SANDBOX_RUNTIME_MODE).strip().lower()
        self.session_factory = session_factory
        self._manager = manager
        self._interactive = interactive or InMemoryRuntime()
        self._signer = SandboxTicketSigner(settings.NLP_AGENT_WEB_SECRET.strip() or "phase4-local-sandbox-secret")

    async def _authorize(self, config: RunnableConfig, *, require_lease: bool = False) -> _AuthorizedModelContext | None:
        from core.session_context import SessionContext

        try:
            context = SessionContext.from_config(config, require=True)
        except ValueError:
            return None
        if self.mode not in {"inmemory", "docker"}:
            return None
        if self.session_factory is None:
            if context.user_id != "local":
                return None
            return _AuthorizedModelContext(context, None, None, None, None)

        async with self.session_factory() as session:
            auth_session = await session.get(SessionModel, context.session_id)
            user = await session.get(UserModel, context.user_id)
            if auth_session is None or user is None:
                return None
            now = _utc_now()
            if (
                str(auth_session.user_id) != context.user_id
                or str(auth_session.workspace_id) != context.workspace_id
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
                or auth_session.authorization_version != user.authorization_version
                or user.status != "active"
                or user.deleted_at is not None
            ):
                return None
            environment = await session.scalar(
                select(SandboxEnvironmentModel).where(
                    SandboxEnvironmentModel.owner_user_id == context.user_id
                )
            )
            lease = None
            if environment is not None:
                lease = await session.scalar(
                    select(SandboxLeaseModel).where(
                        SandboxLeaseModel.environment_id == environment.id,
                        SandboxLeaseModel.user_id == context.user_id,
                        SandboxLeaseModel.auth_session_id == context.session_id,
                        SandboxLeaseModel.state == "active",
                        SandboxLeaseModel.expires_at > now,
                    )
                )
            if require_lease and lease is None:
                return None
            scope = SandboxScope(
                owner_user_id=context.user_id,
                auth_session_id=context.session_id,
                workspace_id=context.workspace_id,
                generation=auth_session.authorization_version,
                lease_expires_at=auth_session.expires_at,
            )
            return _AuthorizedModelContext(
                context,
                scope,
                str(environment.id) if environment is not None else None,
                str(lease.id) if lease is not None else None,
                str(lease.runtime_instance_id) if lease is not None and lease.runtime_instance_id else None,
            )

    def _manager_for_docker(self) -> WarmPoolManager | None:
        if self._manager is not None:
            return self._manager
        if self.session_factory is None:
            return None
        image = settings.NLP_AGENT_SANDBOX_DOCKER_IMAGE_DIGEST.strip()
        if not image:
            return None
        from .docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig

        self._manager = WarmPoolManager(
            session_factory=self.session_factory,
            docker=DockerRuntimeAdapter(DockerRuntimeConfig(image=image)),
            resource_profile_id="python-base",
            ready_target=max(1, settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_TARGET),
            adaptive_policy=(
                AdaptivePoolPolicy(
                    ready_min=settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_MIN,
                    ready_max=settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_MAX,
                    burst_buffer=settings.NLP_AGENT_SANDBOX_BURST_BUFFER,
                )
                if settings.NLP_AGENT_SANDBOX_ADAPTIVE_POOL_ENABLED
                else None
            ),
        )
        return self._manager

    @staticmethod
    def _trace(name: str, *, config: RunnableConfig | None = None, **payload: object) -> None:
        try:
            from core.observability.runtime import global_telemetry
            from core.observability.context import TelemetryContext

            global_telemetry.event(
                name,
                payload=payload,
                context=TelemetryContext.from_config(config),
            )
        except Exception:
            # Tool execution must remain usable when optional telemetry is not configured.
            return

    async def status(self, *, config: RunnableConfig) -> dict[str, object]:
        authorized = await self._authorize(config)
        if authorized is None:
            return _error("not_authorized", "sandbox model context is not authenticated")
        if self.session_factory is None:
            return {"ok": True, "mode": self.mode, "runtime_available": self.mode == "inmemory"}
        from .service import sandbox_lifecycle_service

        async with self.session_factory() as session:
            assert authorized.scope is not None
            payload = await sandbox_lifecycle_service.describe(session, authorized.scope)
        return {"ok": True, "mode": self.mode, **payload}

    async def run_scratch(self, *, source: str, config: RunnableConfig) -> dict[str, object]:
        authorized = await self._authorize(config)
        if authorized is None:
            return _error("not_authorized", "sandbox model context is not authenticated")
        self._trace("sandbox.model.scratch.started", config=config, code_chars=len(source))
        try:
            if self.mode == "inmemory":
                result = await InMemoryRuntime().execute(user_id="scratch", source=source)
            else:
                manager = self._manager_for_docker()
                if manager is None:
                    return _error("sandbox_unavailable", "Docker Sandbox Manager is not configured")
                result = await manager.run_scratch(source=source)
        except Exception as error:
            self._trace("sandbox.model.scratch.failed", config=config, error=type(error).__name__)
            return _error("scratch_failed", str(error)[:500])
        self._trace("sandbox.model.scratch.completed", config=config, status=result.get("status", "completed"))
        return {"ok": True, **result}

    async def run_active(
        self, *, source: str, config: RunnableConfig, confirmed: bool = False
    ) -> dict[str, object]:
        if not confirmed:
            return {
                "ok": False,
                "code": "confirmation_required",
                "error": "sandbox_run_active_kernel requires explicit user confirmation",
            }
        authorized = await self._authorize(config, require_lease=True)
        if authorized is None:
            return _error("lease_required", "an active authenticated Sandbox lease is required")
        if self.mode == "inmemory":
            result = await self._interactive.execute(user_id=authorized.context.user_id, source=source)
            return {"ok": True, "execution_id": str(uuid4()), **result}
        manager = self._manager_for_docker()
        if manager is None or authorized.scope is None or authorized.lease_id is None:
            return _error("sandbox_unavailable", "Docker Sandbox Manager is not configured")
        claim = await manager.claim(authorized.scope, lease_id=authorized.lease_id)
        if claim is None:
            return _error("warming", "Sandbox runtime is warming; retry shortly")
        execution_id = str(uuid4())
        async with self.session_factory.begin() as session:
            session.add(
                SandboxExecutionModel(
                    id=execution_id,
                    environment_id=claim.runtime.environment_id,
                    runtime_instance_id=claim.runtime.id,
                    lease_id=authorized.lease_id,
                    owner_user_id=authorized.context.user_id,
                    workspace_id=authorized.context.workspace_id,
                    actor_type="model",
                    request_id=execution_id,
                    code_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    status="running",
                    generation=claim.runtime.generation,
                    started_at=_utc_now(),
                )
            )
        await default_sandbox_event_store.append(
            execution_id,
            user_id=authorized.context.user_id,
            event_type="execution.started",
            payload={"actor_type": "model"},
        )
        ticket = self._signer.issue(
            SandboxTicketClaims(
                authorized.context.user_id,
                authorized.context.session_id,
                authorized.lease_id,
                str(claim.runtime.id),
                claim.runtime.generation,
                claim.nonce,
            )
        )
        claims = self._signer.verify(
            ticket,
            user_id=authorized.context.user_id,
            auth_session_id=authorized.context.session_id,
        )
        try:
            result = await manager.execute_claimed(
                authorized.scope,
                lease_id=claims.lease_id,
                runtime_id=claims.runtime_id,
                generation=claims.generation,
                nonce=claims.nonce,
                source=source,
            )
        except Exception as error:
            async with self.session_factory.begin() as session:
                execution = await session.get(SandboxExecutionModel, execution_id, with_for_update=True)
                if execution is not None:
                    execution.status = "failed"
                    execution.exit_reason = f"{type(error).__name__}: {error}"[:128]
                    execution.completed_at = _utc_now()
            await default_sandbox_event_store.append(
                execution_id,
                user_id=authorized.context.user_id,
                event_type="execution.failed",
                payload={"error": type(error).__name__},
            )
            raise
        async with self.session_factory.begin() as session:
            execution = await session.get(SandboxExecutionModel, execution_id, with_for_update=True)
            if execution is not None:
                execution.status = str(result.get("status") or "completed")
                execution.completed_at = _utc_now()
                execution.resource_summary_json = {
                    "stdout_bytes": len(str(result.get("stdout") or "").encode("utf-8")),
                    "stderr_bytes": len(str(result.get("stderr") or "").encode("utf-8")),
                }
        await default_sandbox_event_store.append(
            execution_id,
            user_id=authorized.context.user_id,
            event_type="execution.completed",
            payload={"status": result.get("status", "completed")},
        )
        return {"ok": True, "execution_id": execution_id, **result}

    async def explain_execution(self, *, execution_id: str, config: RunnableConfig) -> dict[str, object]:
        authorized = await self._authorize(config)
        if authorized is None or self.session_factory is None:
            return _error("not_authorized", "execution explanation requires an authenticated database session")
        async with self.session_factory() as session:
            execution = await session.get(SandboxExecutionModel, execution_id)
            if execution is None or str(execution.owner_user_id) != authorized.context.user_id:
                return _error("not_found", "sandbox execution was not found")
            summary = {
                "id": str(execution.id),
                "status": execution.status,
                "exit_reason": execution.exit_reason,
                "runtime_instance_id": str(execution.runtime_instance_id) if execution.runtime_instance_id else None,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            }
            events = await default_sandbox_event_store.replay(
                execution_id,
                user_id=authorized.context.user_id,
            )
        return {
            "ok": True,
            "execution": summary,
            "events": events[-50:],
        }

    async def interrupt_own(self, *, execution_id: str, config: RunnableConfig) -> dict[str, object]:
        authorized = await self._authorize(config, require_lease=True)
        if authorized is None or self.session_factory is None:
            return _error("not_authorized", "interrupt requires an authenticated Sandbox lease")
        async with self.session_factory() as session:
            execution = await session.get(SandboxExecutionModel, execution_id)
            if (
                execution is None
                or str(execution.owner_user_id) != authorized.context.user_id
                or execution.lease_id != authorized.lease_id
                or execution.status != "running"
                or execution.runtime_instance_id is None
            ):
                return _error("not_found", "running Sandbox execution was not found")
            runtime_id = str(execution.runtime_instance_id)
        if self.mode == "inmemory":
            return _error("unsupported", "in-memory runtime does not expose process interruption")
        manager = self._manager_for_docker()
        if manager is None:
            return _error("sandbox_unavailable", "Docker Sandbox Manager is not configured")
        await manager.interrupt_runtime(runtime_id)
        return {"ok": True, "execution_id": execution_id, "status": "interrupt_requested"}

    async def reset(self, *, config: RunnableConfig, confirmed: bool = False) -> dict[str, object]:
        if not confirmed:
            return {"ok": False, "code": "confirmation_required", "error": "sandbox_reset requires explicit user confirmation"}
        authorized = await self._authorize(config, require_lease=True)
        if authorized is None or authorized.runtime_id is None:
            return _error("lease_required", "an assigned Sandbox runtime is required")
        if self.mode == "inmemory":
            await self._interactive.restart(user_id=authorized.context.user_id)
            return {"ok": True, "status": "restarted"}
        manager = self._manager_for_docker()
        if manager is None:
            return _error("sandbox_unavailable", "Docker Sandbox Manager is not configured")
        await manager.reset_runtime(authorized.runtime_id)
        return {"ok": True, "status": "restarted", "runtime_id": authorized.runtime_id}


class ExecutionIdInput(BaseModel):
    execution_id: str = Field(min_length=1, max_length=128)


class SourceInput(BaseModel):
    source: str = Field(min_length=1, max_length=20_000)


class ConfirmedSourceInput(SourceInput):
    confirmed: bool = Field(default=False, description="必须由用户明确确认高风险操作")


class ConfirmedInput(BaseModel):
    confirmed: bool = Field(default=False, description="必须由用户明确确认高风险操作")


@tool("sandbox_status")
async def sandbox_status(config: RunnableConfig) -> dict[str, object]:
    """读取当前用户 Sandbox 的状态、租约和运行时摘要。"""
    return await _model_sandbox_service.status(config=config)


@tool("sandbox_run_scratch", args_schema=SourceInput)
async def sandbox_run_scratch(source: str, config: RunnableConfig) -> dict[str, object]:
    """在隔离的 Model Scratch 进程执行代码，不污染用户 Interactive Kernel。"""
    return await _model_sandbox_service.run_scratch(source=source, config=config)


@tool("sandbox_explain_execution", args_schema=ExecutionIdInput)
async def sandbox_explain_execution(execution_id: str, config: RunnableConfig) -> dict[str, object]:
    """读取当前用户自己的 Sandbox 执行摘要和有限事件回放。"""
    return await _model_sandbox_service.explain_execution(execution_id=execution_id, config=config)


@tool("sandbox_interrupt_own", args_schema=ExecutionIdInput)
async def sandbox_interrupt_own(execution_id: str, config: RunnableConfig) -> dict[str, object]:
    """中断当前用户自己的运行中 Sandbox 执行。"""
    return await _model_sandbox_service.interrupt_own(execution_id=execution_id, config=config)


@tool("sandbox_run_active_kernel", args_schema=ConfirmedSourceInput)
async def sandbox_run_active_kernel(
    source: str, confirmed: bool = False, config: RunnableConfig | None = None
) -> dict[str, object]:
    """经用户确认后在用户 Interactive Kernel 执行代码；这是高风险操作。"""
    return await _model_sandbox_service.run_active(source=source, config=config or {}, confirmed=confirmed)


@tool("sandbox_reset", args_schema=ConfirmedInput)
async def sandbox_reset(confirmed: bool = False, config: RunnableConfig | None = None) -> dict[str, object]:
    """经用户确认后销毁当前 Runtime 并重建干净实例；这是高风险操作。"""
    return await _model_sandbox_service.reset(config=config or {}, confirmed=confirmed)


MODEL_SANDBOX_TOOLS: tuple[BaseTool, ...] = (
    sandbox_status,
    sandbox_run_scratch,
    sandbox_explain_execution,
    sandbox_interrupt_own,
    sandbox_run_active_kernel,
    sandbox_reset,
)

_model_sandbox_service = SandboxModelToolService()


def configure_model_sandbox_service(
    *,
    mode: str,
    session_factory: async_sessionmaker[AsyncSession] | None,
    manager: WarmPoolManager | None = None,
) -> SandboxModelToolService:
    """Bind the model tools to the app's authenticated sandbox control plane."""
    global _model_sandbox_service
    _model_sandbox_service = SandboxModelToolService(
        mode=mode,
        session_factory=session_factory,
        manager=manager,
    )
    return _model_sandbox_service
