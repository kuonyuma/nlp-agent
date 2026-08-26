"""Redis RPC boundary between the Web process and the isolated Sandbox Manager.

The Web process owns authentication and tickets, but it never imports Docker
or constructs ``WarmPoolManager``.  The Manager process consumes these signed
internal requests and is the only process allowed to execute Docker calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
from asyncio import Task, create_task, gather
from typing import Any
from uuid import uuid4

from configs.settings import settings

from .contracts import SandboxScope


REQUEST_STREAM = "nova:sandbox:manager:rpc:requests"
RESPONSE_PREFIX = "nova:sandbox:manager:rpc:responses:"
REQUEST_TTL_SECONDS = 60
REQUEST_CLOCK_SKEW_SECONDS = 5


@dataclass(frozen=True, slots=True)
class RemoteRuntime:
    id: str
    generation: int
    environment_id: str | None
    external_runtime_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteRuntimeClaim:
    runtime: RemoteRuntime
    nonce: str | None


def _text(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _signature(secret: str, request_id: str, method: str, payload: str) -> str:
    message = f"{request_id}.{method}.{payload}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _scope_payload(scope: SandboxScope) -> dict[str, object]:
    return {
        "owner_user_id": scope.owner_user_id,
        "auth_session_id": scope.auth_session_id,
        "workspace_id": scope.workspace_id,
        "generation": scope.generation,
        "lease_expires_at": scope.lease_expires_at.isoformat(),
    }


def _scope_from_payload(payload: dict[str, object]) -> SandboxScope:
    expires = datetime.fromisoformat(str(payload["lease_expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return SandboxScope(
        owner_user_id=str(payload["owner_user_id"]),
        auth_session_id=str(payload["auth_session_id"]),
        workspace_id=str(payload["workspace_id"]),
        generation=int(payload["generation"]),
        lease_expires_at=expires,
    )


class RedisSandboxManagerRpcClient:
    """Web-side Manager port implemented over a bounded Redis RPC stream."""

    def __init__(
        self,
        client: Any,
        *,
        secret: str,
        request_stream: str = REQUEST_STREAM,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client = client
        self._secret = secret
        self._request_stream = request_stream
        self._timeout_seconds = max(1.0, timeout_seconds)

    async def _request(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        request_id = uuid4().hex
        response_stream = f"{RESPONSE_PREFIX}{request_id}"
        issued_at = time.time()
        body = _json(
            {
                **payload,
                "issued_at": issued_at,
                "expires_at": issued_at + REQUEST_TTL_SECONDS,
            }
        )
        await self._client.xadd(
            self._request_stream,
            {
                "request_id": request_id,
                "response_stream": response_stream,
                "method": method,
                "payload": body,
                "signature": _signature(self._secret, request_id, method, body),
            },
            maxlen=10_000,
            approximate=True,
        )
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            rows = await self._client.xread({response_stream: "0-0"}, count=1, block=1_000)
            for _stream, messages in rows or ():
                for _message_id, fields in messages:
                    parsed = {_text(key): _text(value) for key, value in fields.items()}
                    if parsed.get("request_id") != request_id:
                        continue
                    if parsed.get("ok") != "1":
                        raise RuntimeError(parsed.get("error", "Sandbox Manager RPC failed"))
                    try:
                        result = json.loads(parsed.get("payload", "{}"))
                    except json.JSONDecodeError as error:
                        raise RuntimeError("Sandbox Manager returned invalid RPC JSON") from error
                    if not isinstance(result, dict):
                        raise RuntimeError("Sandbox Manager returned an invalid RPC payload")
                    return result
        raise TimeoutError(f"Sandbox Manager RPC timed out: {method}")

    async def claim(self, scope: SandboxScope, *, lease_id: str) -> RemoteRuntimeClaim | None:
        result = await self._request("claim", {"scope": _scope_payload(scope), "lease_id": lease_id})
        claim = result.get("claim")
        if claim is None:
            return None
        if not isinstance(claim, dict) or not isinstance(claim.get("runtime"), dict):
            raise RuntimeError("Sandbox Manager returned an invalid claim")
        runtime = claim["runtime"]
        return RemoteRuntimeClaim(
            runtime=RemoteRuntime(
                id=str(runtime["id"]),
                generation=int(runtime["generation"]),
                environment_id=str(runtime["environment_id"]) if runtime.get("environment_id") else None,
                external_runtime_id=str(runtime["external_runtime_id"]) if runtime.get("external_runtime_id") else None,
            ),
            nonce=str(claim["nonce"]) if claim.get("nonce") else None,
        )

    async def execute_claimed(
        self,
        scope: SandboxScope,
        *,
        lease_id: str,
        runtime_id: str,
        generation: int,
        nonce: str | None,
        source: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> dict[str, object]:
        return await self._request(
            "execute_claimed",
            {
                "scope": _scope_payload(scope),
                "lease_id": lease_id,
                "runtime_id": runtime_id,
                "generation": generation,
                "nonce": nonce,
                "source": source,
                "trace_id": trace_id,
                "span_id": span_id,
            },
        )

    async def reset_runtime(
        self,
        scope: SandboxScope,
        *,
        lease_id: str,
        runtime_id: str,
        generation: int | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        await self._request(
            "reset_runtime",
            {
                "scope": _scope_payload(scope),
                "lease_id": lease_id,
                "runtime_id": runtime_id,
                "generation": generation,
                "trace_id": trace_id,
                "span_id": span_id,
            },
        )

    async def interrupt_runtime(
        self,
        scope: SandboxScope,
        *,
        lease_id: str,
        runtime_id: str,
        generation: int | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        await self._request(
            "interrupt_runtime",
            {
                "scope": _scope_payload(scope),
                "lease_id": lease_id,
                "runtime_id": runtime_id,
                "generation": generation,
                "trace_id": trace_id,
                "span_id": span_id,
            },
        )

    async def capacity_snapshot(self) -> dict[str, object]:
        return await self._request("capacity_snapshot", {})

    async def run_scratch(
        self,
        *,
        source: str,
        timeout_seconds: int = 15,
        output_limit_bytes: int = 1_000_000,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> dict[str, object]:
        return await self._request(
            "run_scratch",
            {
                "source": source,
                "timeout_seconds": timeout_seconds,
                "output_limit_bytes": output_limit_bytes,
                "trace_id": trace_id,
                "span_id": span_id,
            },
        )

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


class RedisSandboxManagerRpcServer:
    """Manager-side dispatcher for the Redis RPC stream."""

    def __init__(self, client: Any, *, manager: Any, secret: str, request_stream: str = REQUEST_STREAM) -> None:
        self._client = client
        self._manager = manager
        self._secret = secret
        self._request_stream = request_stream
        self._cursor = "0-0"
        self._tasks: set[Task[None]] = set()

    async def process_once(self, *, block_ms: int = 100) -> bool:
        rows = await self._client.xread({self._request_stream: self._cursor}, count=1, block=max(1, block_ms))
        if not rows:
            return False
        for _stream, messages in rows:
            for message_id, raw_fields in messages:
                self._cursor = _text(message_id)
                fields = {_text(key): _text(value) for key, value in raw_fields.items()}
                task = create_task(self._handle(fields), name=f"sandbox-manager-rpc:{fields.get('request_id', '')}")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        return True

    async def _handle(self, fields: dict[str, str]) -> None:
        request_id = fields.get("request_id", "")
        response_stream = fields.get("response_stream", f"{RESPONSE_PREFIX}{request_id}")
        method = fields.get("method", "")
        body = fields.get("payload", "{}")
        try:
            if not hmac.compare_digest(
                fields.get("signature", ""), _signature(self._secret, request_id, method, body)
            ):
                raise PermissionError("invalid Sandbox Manager RPC signature")
            dedupe = getattr(self._client, "set", None)
            if callable(dedupe):
                try:
                    accepted = await dedupe(
                        f"nova:sandbox:manager:rpc:handled:{request_id}",
                        "1",
                        nx=True,
                        ex=600,
                    )
                except Exception as error:
                    raise RuntimeError("Sandbox Manager RPC replay guard is unavailable") from error
                if not accepted:
                    # Another Manager owns this request.  Do not publish an
                    # error to the shared response stream: the winning
                    # Manager's response is the only authoritative result.
                    return
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Sandbox Manager RPC payload must be an object")
            now = time.time()
            issued_at = payload.get("issued_at")
            expires_at = payload.get("expires_at")
            if (
                not isinstance(issued_at, (int, float))
                or not isinstance(expires_at, (int, float))
                or issued_at > now + REQUEST_CLOCK_SKEW_SECONDS
                or expires_at <= now
                or expires_at - issued_at > REQUEST_TTL_SECONDS + REQUEST_CLOCK_SKEW_SECONDS
            ):
                raise PermissionError("expired or invalid Sandbox Manager RPC request")
            result = await self._dispatch(method, payload)
            ok, encoded, error = "1", _json(result), ""
        except Exception as exc:
            ok, encoded, error = "0", "{}", f"{type(exc).__name__}: {exc}"[:500]
        await self._client.xadd(
            response_stream,
            {"request_id": request_id, "ok": ok, "payload": encoded, "error": error},
            maxlen=10,
            approximate=True,
        )
        await self._client.expire(response_stream, 60)

    async def _dispatch(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        trace = getattr(self._manager, "_trace", None)
        if trace is not None and payload.get("trace_id"):
            trace(
                "sandbox.manager.rpc.dispatch",
                trace_id=str(payload["trace_id"]),
                span_id=str(payload.get("span_id") or ""),
                method=method,
            )
        if method == "claim":
            claim = await self._manager.claim(_scope_from_payload(payload["scope"]), lease_id=str(payload["lease_id"]))
            if claim is None:
                return {"claim": None}
            runtime = claim.runtime
            return {
                "claim": {
                    "runtime": {
                        "id": str(runtime.id),
                        "generation": runtime.generation,
                        "environment_id": str(runtime.environment_id) if runtime.environment_id else None,
                        "external_runtime_id": runtime.external_runtime_id,
                    },
                    "nonce": claim.nonce,
                }
            }
        if method == "execute_claimed":
            return await self._manager.execute_claimed(
                _scope_from_payload(payload["scope"]),
                lease_id=str(payload["lease_id"]),
                runtime_id=str(payload["runtime_id"]),
                generation=int(payload["generation"]),
                nonce=str(payload["nonce"]) if payload.get("nonce") else None,
                source=str(payload["source"]),
                trace_id=str(payload["trace_id"]) if payload.get("trace_id") else None,
                span_id=str(payload["span_id"]) if payload.get("span_id") else None,
            )
        if method == "reset_runtime":
            await self._manager.reset_runtime(
                _scope_from_payload(payload["scope"]),
                lease_id=str(payload["lease_id"]),
                runtime_id=str(payload["runtime_id"]),
                generation=int(payload["generation"]) if payload.get("generation") is not None else None,
                trace_id=str(payload["trace_id"]) if payload.get("trace_id") else None,
                span_id=str(payload["span_id"]) if payload.get("span_id") else None,
            )
            return {"ok": True}
        if method == "interrupt_runtime":
            await self._manager.interrupt_runtime(
                _scope_from_payload(payload["scope"]),
                lease_id=str(payload["lease_id"]),
                runtime_id=str(payload["runtime_id"]),
                generation=int(payload["generation"]) if payload.get("generation") is not None else None,
                trace_id=str(payload["trace_id"]) if payload.get("trace_id") else None,
                span_id=str(payload["span_id"]) if payload.get("span_id") else None,
            )
            return {"ok": True}
        if method == "capacity_snapshot":
            return dict(await self._manager.capacity_snapshot())
        if method == "run_scratch":
            return await self._manager.run_scratch(
                source=str(payload["source"]),
                timeout_seconds=int(payload.get("timeout_seconds", 15)),
                output_limit_bytes=int(payload.get("output_limit_bytes", 1_000_000)),
                trace_id=str(payload["trace_id"]) if payload.get("trace_id") else None,
                span_id=str(payload["span_id"]) if payload.get("span_id") else None,
            )
        raise ValueError(f"unsupported Sandbox Manager RPC method: {method}")

    async def close(self) -> None:
        if self._tasks:
            await gather(*self._tasks, return_exceptions=True)
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def create_sandbox_manager_rpc_client() -> RedisSandboxManagerRpcClient | None:
    redis_url = settings.NLP_AGENT_REDIS_URL.strip()
    secret = settings.NLP_AGENT_WEB_SECRET.strip()
    if not redis_url or not secret:
        return None
    from redis.asyncio import Redis

    return RedisSandboxManagerRpcClient(
        Redis.from_url(redis_url, decode_responses=True),
        secret=secret,
        timeout_seconds=settings.NLP_AGENT_SANDBOX_MANAGER_RPC_TIMEOUT_S,
    )


def create_sandbox_manager_rpc_server(manager: Any) -> RedisSandboxManagerRpcServer | None:
    redis_url = settings.NLP_AGENT_REDIS_URL.strip()
    secret = settings.NLP_AGENT_WEB_SECRET.strip()
    if not redis_url or not secret:
        return None
    from redis.asyncio import Redis

    return RedisSandboxManagerRpcServer(
        Redis.from_url(redis_url, decode_responses=True), manager=manager, secret=secret
    )
