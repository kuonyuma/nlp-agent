"""Unified, policy-governed tool catalog and execution runtime."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import AsyncExitStack
from enum import Enum
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from utils.logger import get_logger
from core.tool_safety import (
    ToolAuditEvent,
    ToolAuditLog,
    ToolAuthorizationManager,
    global_tool_audit_log,
    global_tool_authorizations,
)


logger = get_logger("nlp_agent.tool_runtime")
_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


class ToolSource(str, Enum):
    BUILTIN = "builtin"
    CUSTOM = "custom"
    MCP = "mcp"
    ORCHESTRATION = "orchestration"


class ToolScope(str, Enum):
    COORDINATOR = "coordinator"
    WORKER = "worker"


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolLockScope(str, Enum):
    NONE = "none"
    SESSION = "session"
    GLOBAL = "global"


class ToolRetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=5)
    retryable_kinds: frozenset[str] = Field(
        default_factory=lambda: frozenset({"timeout", "network", "rate_limit"})
    )
    base_delay_s: float = Field(default=0.25, ge=0, le=30)
    max_delay_s: float = Field(default=4.0, ge=0, le=120)
    jitter_ratio: float = Field(default=0.20, ge=0, le=1)

    @field_validator("retryable_kinds")
    @classmethod
    def validate_retryable_kinds(cls, values: frozenset[str]) -> frozenset[str]:
        supported = {"timeout", "network", "rate_limit"}
        unknown = values.difference(supported)
        if unknown:
            raise ValueError(f"unsupported retry kinds: {', '.join(sorted(unknown))}")
        return values

    @model_validator(mode="after")
    def validate_delays(self) -> "ToolRetryPolicy":
        if self.max_delay_s < self.base_delay_s:
            raise ValueError("max_delay_s must be greater than or equal to base_delay_s")
        return self

    def delay_for(self, failed_attempt: int) -> float:
        delay = self.base_delay_s * (2 ** max(0, failed_attempt - 1))
        if delay and self.jitter_ratio:
            delay *= random.uniform(1 - self.jitter_ratio, 1 + self.jitter_ratio)
        return min(self.max_delay_s, max(0, delay))


class ToolDescriptor(BaseModel):
    """Pydantic-v2 validated metadata plus a factory for one executable tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    description: str
    source: ToolSource
    provider: str = "core"
    scopes: frozenset[ToolScope]
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    risk: ToolRisk = ToolRisk.LOW
    read_only: bool = False
    idempotent: bool = False
    concurrency_safe: bool = False
    exclusive: bool = False
    lock_scope: ToolLockScope = ToolLockScope.NONE
    timeout_s: float = Field(default=30.0, gt=0, le=1800)
    max_concurrency: int = Field(default=0, ge=0, le=100)
    retry: ToolRetryPolicy = Field(default_factory=ToolRetryPolicy)
    enabled: bool = True
    factory: Callable[[], BaseTool] = Field(exclude=True, repr=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _TOOL_NAME.fullmatch(value):
            raise ValueError(
                "tool name must start with a letter/underscore, contain only "
                "letters, digits, underscore or hyphen, and be at most 64 characters"
            )
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: frozenset[str]) -> frozenset[str]:
        for value in values:
            if not value or value.strip() != value or " " in value:
                raise ValueError(f"invalid capability: {value!r}")
        return values

    @model_validator(mode="after")
    def validate_concurrency_contract(self) -> "ToolDescriptor":
        if self.exclusive and self.concurrency_safe:
            raise ValueError("exclusive tools cannot be concurrency_safe")
        if self.exclusive and self.lock_scope == ToolLockScope.NONE:
            object.__setattr__(self, "lock_scope", ToolLockScope.GLOBAL)
        if self.lock_scope != ToolLockScope.NONE and self.concurrency_safe:
            raise ValueError("locked tools cannot be concurrency_safe")
        if not self.read_only and self.concurrency_safe:
            raise ValueError("only read-only tools may be marked concurrency_safe")
        if self.retry.max_attempts > 1 and not (self.read_only or self.idempotent):
            raise ValueError("retries require a read-only or explicitly idempotent tool")
        return self

    def instantiate(self) -> BaseTool:
        tool = self.factory()
        if tool.name != self.name:
            raise ValueError(
                f"tool factory for {self.name!r} produced mismatched name {tool.name!r}"
            )
        return tool


class ToolGrantRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ToolScope
    session_id: str = ""
    profile: str = ""
    allowed_tools: frozenset[str] = Field(default_factory=frozenset)
    allowed_capabilities: frozenset[str] = Field(default_factory=frozenset)
    denied_tools: frozenset[str] = Field(default_factory=frozenset)
    denied_capabilities: frozenset[str] = Field(default_factory=frozenset)
    allow_high_risk: bool = False


class ToolGrantSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str = "1"
    role: ToolScope
    session_id: str = ""
    profile: str = ""
    granted_tools: tuple[str, ...]
    granted_capabilities: tuple[str, ...]
    catalog_revision: int
    created_at: float = Field(default_factory=time.time)


class ToolExecutionError(BaseModel):
    kind: Literal[
        "not_found",
        "permission_denied",
        "validation",
        "timeout",
        "execution",
        "network",
        "rate_limit",
        "tool_error",
    ]
    message: str
    retryable: bool = False


class ToolExecutionResult(BaseModel):
    tool_name: str
    ok: bool
    output: Any = None
    error: ToolExecutionError | None = None
    duration_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> "ToolExecutionResult":
        if self.ok and self.error is not None:
            raise ValueError("successful result cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("failed result must contain an error")
        return self

    def to_model_content(self) -> str:
        if self.ok:
            if isinstance(self.output, str):
                return self.output
            return json.dumps(self.output, ensure_ascii=False, default=str)
        return json.dumps(
            {
                "ok": False,
                "tool": self.tool_name,
                "error": self.error.model_dump() if self.error else None,
            },
            ensure_ascii=False,
        )


class ToolCatalog:
    """Single source of truth for tool definitions and collision policy."""

    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self.revision = 0

    def register(self, descriptor: ToolDescriptor, *, replace: bool = False) -> None:
        existing = self._descriptors.get(descriptor.name)
        if existing is not None and not replace:
            raise ValueError(
                f"tool name collision: {descriptor.name!r} is already provided by "
                f"{existing.source.value}:{existing.provider}"
            )
        self._descriptors[descriptor.name] = descriptor
        self.revision += 1
        logger.info(
            "Tool registered",
            tool_name=descriptor.name,
            source=descriptor.source.value,
            provider=descriptor.provider,
        )

    def unregister(self, name: str) -> None:
        if self._descriptors.pop(name, None) is not None:
            self.revision += 1

    def unregister_provider(self, source: ToolSource, provider: str) -> int:
        names = [
            name
            for name, descriptor in self._descriptors.items()
            if descriptor.source == source and descriptor.provider == provider
        ]
        for name in names:
            self._descriptors.pop(name, None)
        if names:
            self.revision += 1
        return len(names)

    def get(self, name: str) -> ToolDescriptor | None:
        return self._descriptors.get(name)

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(
            sorted(
                self._descriptors.values(),
                key=lambda item: (item.source == ToolSource.MCP, item.name),
            )
        )

    def names(self) -> tuple[str, ...]:
        return tuple(descriptor.name for descriptor in self.descriptors())


class ToolPolicyResolver:
    """Resolve explicit tool/capability requests into an immutable grant."""

    def __init__(
        self,
        catalog: ToolCatalog,
        authorization: ToolAuthorizationManager,
        *,
        policy_version: str = "2",
    ) -> None:
        self.catalog = catalog
        self.authorization = authorization
        self.policy_version = policy_version

    def resolve(self, request: ToolGrantRequest) -> ToolGrantSnapshot:
        unknown = request.allowed_tools.difference(self.catalog.names())
        if unknown:
            raise ValueError(f"unknown tools requested: {', '.join(sorted(unknown))}")

        granted: list[ToolDescriptor] = []
        for descriptor in self.catalog.descriptors():
            if not descriptor.enabled or request.role not in descriptor.scopes:
                continue
            explicitly_named = descriptor.name in request.allowed_tools
            capability_match = bool(
                descriptor.capabilities.intersection(request.allowed_capabilities)
            )
            if not explicitly_named and not capability_match:
                continue
            if descriptor.name in request.denied_tools:
                continue
            if descriptor.capabilities.intersection(request.denied_capabilities):
                continue
            if descriptor.risk == ToolRisk.HIGH and not (
                request.allow_high_risk
                and self.authorization.is_granted(request.session_id, descriptor.name)
            ):
                continue
            granted.append(descriptor)

        granted_capabilities = sorted(
            set().union(*(descriptor.capabilities for descriptor in granted)) if granted else set()
        )
        return ToolGrantSnapshot(
            policy_version=self.policy_version,
            role=request.role,
            session_id=request.session_id,
            profile=request.profile,
            granted_tools=tuple(descriptor.name for descriptor in granted),
            granted_capabilities=tuple(granted_capabilities),
            catalog_revision=self.catalog.revision,
        )


class ToolExecutor:
    """Pydantic-v2 validation, timeouts, error normalization, and telemetry."""

    def __init__(
        self,
        authorization: ToolAuthorizationManager = global_tool_authorizations,
        audit_log: ToolAuditLog = global_tool_audit_log,
    ) -> None:
        self.authorization = authorization
        self.audit_log = audit_log
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._global_locks: dict[str, asyncio.Lock] = {}
        self._session_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def execute(
        self,
        descriptor: ToolDescriptor,
        tool: BaseTool,
        arguments: Mapping[str, Any] | None,
        grant: ToolGrantSnapshot,
        config: RunnableConfig | None = None,
    ) -> ToolExecutionResult:
        started = time.monotonic()
        argument_keys = tuple(sorted(str(key) for key in (arguments or {})))
        if descriptor.risk == ToolRisk.HIGH and not self.authorization.is_granted(
            grant.session_id, descriptor.name
        ):
            result = self._failure(
                descriptor.name,
                started,
                "permission_denied",
                "high-risk tool requires an active session grant",
                attempts=0,
            )
            await self._audit(
                descriptor,
                grant,
                phase="denied",
                outcome="denied",
                error_kind="permission_denied",
                attempt=0,
                argument_keys=argument_keys,
            )
            return result
        try:
            params = self._validate_arguments(tool, dict(arguments or {}))
        except Exception as error:
            result = self._failure(
                descriptor.name, started, "validation", str(error), attempts=0
            )
            await self._audit(
                descriptor,
                grant,
                phase="completed",
                outcome="error",
                error_kind="validation",
                attempt=0,
                argument_keys=argument_keys,
            )
            return result

        async def invoke() -> Any:
            return await tool.ainvoke(params, config=config)

        async with AsyncExitStack() as stack:
            semaphore = self._semaphore_for(descriptor)
            if semaphore is not None:
                await stack.enter_async_context(semaphore)
            lock = self._exclusive_lock(descriptor, grant.session_id)
            if lock is not None:
                await stack.enter_async_context(lock)

            final: ToolExecutionResult | None = None
            for attempt in range(1, descriptor.retry.max_attempts + 1):
                await self._audit(
                    descriptor,
                    grant,
                    phase="attempt",
                    outcome="started",
                    attempt=attempt,
                    argument_keys=argument_keys,
                )
                try:
                    output = await asyncio.wait_for(invoke(), timeout=descriptor.timeout_s)
                    tool_error = self._detect_tool_error(output)
                    if tool_error is None:
                        final = ToolExecutionResult(
                            tool_name=descriptor.name,
                            ok=True,
                            output=output,
                            duration_ms=int((time.monotonic() - started) * 1000),
                            attempts=attempt,
                        )
                    else:
                        final = self._failure(
                            descriptor.name,
                            started,
                            "tool_error",
                            tool_error,
                            attempts=attempt,
                        )
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    can_retry = descriptor.read_only or descriptor.idempotent
                    final = self._failure(
                        descriptor.name,
                        started,
                        "timeout",
                        f"tool timed out after {descriptor.timeout_s:g} seconds",
                        retryable=can_retry and "timeout" in descriptor.retry.retryable_kinds,
                        attempts=attempt,
                    )
                except Exception as error:
                    kind, retryable = self._classify_exception(error)
                    retryable = bool(
                        retryable
                        and (descriptor.read_only or descriptor.idempotent)
                        and kind in descriptor.retry.retryable_kinds
                    )
                    final = self._failure(
                        descriptor.name,
                        started,
                        kind,
                        f"{type(error).__name__}: {error}",
                        retryable=retryable,
                        attempts=attempt,
                    )

                if final.ok or not self._should_retry(descriptor, final, attempt):
                    break
                await self._audit(
                    descriptor,
                    grant,
                    phase="retry",
                    outcome="error",
                    error_kind=final.error.kind if final.error else "execution",
                    attempt=attempt,
                    argument_keys=argument_keys,
                )
                await asyncio.sleep(descriptor.retry.delay_for(attempt))

        assert final is not None
        await self._audit(
            descriptor,
            grant,
            phase="completed",
            outcome="success" if final.ok else "error",
            error_kind=final.error.kind if final.error else "",
            attempt=final.attempts,
            duration_ms=final.duration_ms,
            argument_keys=argument_keys,
        )
        return final

    @staticmethod
    def _validate_arguments(tool: BaseTool, arguments: dict[str, Any]) -> dict[str, Any]:
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema.model_validate(arguments).model_dump(exclude_unset=True)
        return arguments

    @staticmethod
    def _detect_tool_error(output: Any) -> str | None:
        if isinstance(output, Mapping) and output.get("error"):
            return str(output["error"])
        if not isinstance(output, str):
            return None
        stripped = output.strip()
        if stripped.startswith("Error:") or stripped.startswith("错误："):
            return stripped
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except Exception:
                return None
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload["error"])
        return None

    def _semaphore_for(self, descriptor: ToolDescriptor) -> asyncio.Semaphore | None:
        if descriptor.max_concurrency <= 0:
            return None
        return self._semaphores.setdefault(
            descriptor.name, asyncio.Semaphore(descriptor.max_concurrency)
        )

    def _exclusive_lock(
        self, descriptor: ToolDescriptor, session_id: str
    ) -> asyncio.Lock | None:
        if descriptor.lock_scope == ToolLockScope.GLOBAL:
            return self._global_locks.setdefault(descriptor.name, asyncio.Lock())
        if descriptor.lock_scope == ToolLockScope.SESSION:
            return self._session_locks.setdefault(
                (session_id, descriptor.name), asyncio.Lock()
            )
        return None

    @staticmethod
    def _classify_exception(error: Exception) -> tuple[str, bool]:
        text = f"{type(error).__name__}: {error}".lower()
        status = getattr(error, "status_code", None)
        if status == 429 or "rate limit" in text or "ratelimit" in text:
            return "rate_limit", True
        if isinstance(error, ConnectionError) or any(
            marker in text
            for marker in ("connection", "network", "temporarily unavailable", "dns")
        ):
            return "network", True
        return "execution", False

    @staticmethod
    def _should_retry(
        descriptor: ToolDescriptor,
        result: ToolExecutionResult,
        attempt: int,
    ) -> bool:
        return bool(
            not result.ok
            and result.error
            and result.error.retryable
            and result.error.kind in descriptor.retry.retryable_kinds
            and attempt < descriptor.retry.max_attempts
            and (descriptor.read_only or descriptor.idempotent)
        )

    async def _audit(
        self,
        descriptor: ToolDescriptor,
        grant: ToolGrantSnapshot,
        *,
        phase: str,
        outcome: str,
        attempt: int,
        error_kind: str = "",
        duration_ms: int = 0,
        argument_keys: tuple[str, ...] = (),
    ) -> None:
        try:
            await self.audit_log.emit(
                ToolAuditEvent(
                    session_id=grant.session_id,
                    role=grant.role.value,
                    profile=grant.profile,
                    tool_name=descriptor.name,
                    provider=descriptor.provider,
                    phase=phase,
                    attempt=attempt,
                    outcome=outcome,
                    error_kind=error_kind,
                    duration_ms=duration_ms,
                    argument_keys=argument_keys,
                )
            )
        except Exception as error:
            logger.warning("Tool audit write failed", error=str(error))

    @staticmethod
    def _failure(
        tool_name: str,
        started: float,
        kind: str,
        message: str,
        *,
        retryable: bool = False,
        attempts: int = 1,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_name,
            ok=False,
            error=ToolExecutionError(kind=kind, message=message, retryable=retryable),
            duration_ms=int((time.monotonic() - started) * 1000),
            attempts=attempts,
        )


class ToolSet:
    """One immutable grant used by both model binding and actual execution."""

    def __init__(
        self,
        snapshot: ToolGrantSnapshot,
        descriptors: Iterable[ToolDescriptor],
        executor: ToolExecutor,
    ) -> None:
        self.snapshot = snapshot
        self.descriptors = tuple(descriptors)
        self._descriptor_by_name = {item.name: item for item in self.descriptors}
        self._tools = {item.name: item.instantiate() for item in self.descriptors}
        self.executor = executor

    @property
    def tools(self) -> list[BaseTool]:
        return [self._tools[name] for name in self.snapshot.granted_tools]

    @property
    def names(self) -> tuple[str, ...]:
        return self.snapshot.granted_tools

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        config: RunnableConfig | None = None,
    ) -> ToolExecutionResult:
        descriptor = self._descriptor_by_name.get(name)
        tool = self._tools.get(name)
        if descriptor is None or tool is None:
            return ToolExecutionResult(
                tool_name=name,
                ok=False,
                error=ToolExecutionError(
                    kind="permission_denied",
                    message=f"tool {name!r} is not granted in this runtime",
                ),
                attempts=0,
            )
        return await self.executor.execute(
            descriptor, tool, arguments, self.snapshot, config
        )

    async def execute_many(
        self,
        calls: list[tuple[str, Mapping[str, Any] | None]],
        config: RunnableConfig | None = None,
    ) -> list[ToolExecutionResult]:
        results: list[ToolExecutionResult] = []
        index = 0
        while index < len(calls):
            name, arguments = calls[index]
            descriptor = self._descriptor_by_name.get(name)
            if descriptor is None or not descriptor.concurrency_safe:
                results.append(await self.execute(name, arguments, config))
                index += 1
                continue
            batch: list[tuple[str, Mapping[str, Any] | None]] = []
            while index < len(calls):
                batch_name, batch_arguments = calls[index]
                batch_descriptor = self._descriptor_by_name.get(batch_name)
                if batch_descriptor is None or not batch_descriptor.concurrency_safe:
                    break
                batch.append((batch_name, batch_arguments))
                index += 1
            results.extend(
                await asyncio.gather(
                    *(self.execute(item_name, item_args, config) for item_name, item_args in batch)
                )
            )
        return results


class ToolRuntime:
    def __init__(
        self,
        *,
        authorization: ToolAuthorizationManager = global_tool_authorizations,
        audit_log: ToolAuditLog = global_tool_audit_log,
    ) -> None:
        self.catalog = ToolCatalog()
        self.authorization = authorization
        self.audit_log = audit_log
        self.policy = ToolPolicyResolver(self.catalog, authorization)
        self.executor = ToolExecutor(authorization, audit_log)
        self._mcp_runtime: Any | None = None

    def grant_high_risk(
        self,
        *,
        session_id: str,
        tool_name: str,
        granted_by: str,
        reason: str = "",
        ttl_s: float = 300,
    ):
        descriptor = self.catalog.get(tool_name)
        if descriptor is None:
            raise ValueError(f"unknown tool: {tool_name}")
        if descriptor.risk != ToolRisk.HIGH:
            raise ValueError(f"tool {tool_name!r} is not high-risk")
        return self.authorization.grant(
            session_id=session_id,
            tool_name=tool_name,
            granted_by=granted_by,
            reason=reason,
            ttl_s=ttl_s,
        )

    def build_toolset(self, request: ToolGrantRequest) -> ToolSet:
        snapshot = self.policy.resolve(request)
        descriptors = [
            descriptor
            for name in snapshot.granted_tools
            if (descriptor := self.catalog.get(name)) is not None
        ]
        return ToolSet(snapshot, descriptors, self.executor)

    def restore_toolset(self, snapshot: ToolGrantSnapshot) -> ToolSet:
        """Restore an exact persisted grant without broadening it through new policy."""
        missing = [name for name in snapshot.granted_tools if self.catalog.get(name) is None]
        if missing:
            raise ValueError(
                "persisted tool grant references unavailable tools: " + ", ".join(missing)
            )
        descriptors = [self.catalog.get(name) for name in snapshot.granted_tools]
        invalid_scope = [
            descriptor.name
            for descriptor in descriptors
            if descriptor is not None and snapshot.role not in descriptor.scopes
        ]
        if invalid_scope:
            raise ValueError(
                "persisted tool grant violates current role scopes: "
                + ", ".join(invalid_scope)
            )
        expired_high_risk = [
            descriptor.name
            for descriptor in descriptors
            if descriptor is not None
            and descriptor.risk == ToolRisk.HIGH
            and not self.authorization.is_granted(snapshot.session_id, descriptor.name)
        ]
        if expired_high_risk:
            raise PermissionError(
                "persisted high-risk grants expired or were revoked: "
                + ", ".join(expired_high_risk)
            )
        return ToolSet(snapshot, [item for item in descriptors if item is not None], self.executor)

    async def start_mcp(self, configs: Mapping[str, Any]) -> None:
        if not configs:
            return
        from core.mcp_runtime import MCPRuntime

        if self._mcp_runtime is None:
            self._mcp_runtime = MCPRuntime(self.catalog)
        await self._mcp_runtime.connect_all(configs)

    async def close(self) -> None:
        if self._mcp_runtime is not None:
            await self._mcp_runtime.close()
            self._mcp_runtime = None


global_tool_runtime = ToolRuntime()
