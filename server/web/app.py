"""FastAPI same-origin adapter for the lifecycle-owning BackendGateway."""

import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response, Security, WebSocket, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyCookie
from starlette.middleware.trustedhost import TrustedHostMiddleware

from configs.settings import settings
from core.identity import AccessDeniedError, AuthenticatedPrincipal
from gateway.contracts import (
    GatewayNotStartedError,
    InjectMessageRequest,
    ResourceNotFoundError,
    SubmitTurnRequest,
    TurnConflictError,
)
from gateway.core import BackendGateway
from server.web.auth import (
    AuthenticationError,
    CsrfRejectedError,
    OriginRejectedError,
    SameOriginSessionAuth,
    SessionClaims,
)
from server.web.contracts import (
    CreateSessionBody,
    InjectChatBody,
    SubmitChatBody,
    ToolApprovalBody,
    UpdateSettingsBody,
)
from server.web.protocol import control_event
from server.web.websocket import WebSocketHub, websocket_endpoint


GatewayFactory = Callable[[], BackendGateway]


def _problem(
    request: Request,
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body: dict[str, Any] = {
        "type": f"urn:nlp-agent:error:{code}",
        "title": title,
        "status": status_code,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status_code, media_type="application/problem+json")


def _public_runtime_settings() -> dict[str, Any]:
    raw = settings._config
    models = {
        name: {
            "provider": item.get("provider"),
            "model_id": item.get("model_id"),
            "context_window_tokens": item.get("context_window_tokens"),
            "max_output_tokens": item.get("max_output_tokens"),
            "capabilities": item.get("capabilities", {}),
        }
        for name, item in raw.get("models", {}).items()
    }
    presets = {
        name: {
            "model": item.get("model"),
            "thinking": item.get("thinking", {}),
            "generation": item.get("generation", {}),
        }
        for name, item in raw.get("model_presets", {}).items()
    }
    return {
        "defaults": raw.get("defaults", {}),
        "model_routes": raw.get("model_routes", {}),
        "models": models,
        "model_presets": presets,
        "protocol": {
            "http": "/api/v1",
            "websocket": "/ws/v1",
            "version": "1",
        },
    }


def create_app(
    *,
    gateway_factory: GatewayFactory = BackendGateway,
    auth: SameOriginSessionAuth | None = None,
) -> FastAPI:
    web_config = settings.web_runtime
    auth = auth or SameOriginSessionAuth.from_config(web_config)
    hub = WebSocketHub(
        max_connections=int(web_config.get("ws_max_connections", 200)),
        max_connections_per_user=int(
            web_config.get("ws_max_connections_per_user", 10)
        ),
    )
    stream_queue_size = int(settings.gateway_runtime.get("stream_queue_size", 500))
    max_ws_message_bytes = int(web_config.get("max_ws_message_bytes", 1_048_576))
    ws_send_queue_size = int(web_config.get("ws_send_queue_size", 256))
    ws_send_timeout_s = float(web_config.get("ws_send_timeout_s", 10))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        gateway = gateway_factory()
        app.state.gateway = gateway
        await gateway.start()
        try:
            yield
        finally:
            await gateway.begin_shutdown()
            await hub.close()
            await gateway.close()

    app = FastAPI(
        title="NLP Agent Web API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.auth = auth
    app.state.hub = hub
    cookie_auth = APIKeyCookie(name=auth.cookie_name, auto_error=False)
    allowed_hosts = list(web_config.get("allowed_hosts", ["127.0.0.1", "localhost"]))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or secrets.token_hex(16)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    def current_claims(
        token: Annotated[str | None, Security(cookie_auth)],
    ) -> SessionClaims:
        return auth.authenticate(token)

    def current_principal(
        claims: Annotated[SessionClaims, Depends(current_claims)],
    ) -> AuthenticatedPrincipal:
        return claims.principal()

    def write_access(
        request: Request,
        claims: Annotated[SessionClaims, Depends(current_claims)],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> SessionClaims:
        auth.require_same_origin(request.headers.get("origin"), request.headers.get("host"))
        auth.require_csrf(claims, csrf_token)
        return claims

    Principal = Annotated[AuthenticatedPrincipal, Depends(current_principal)]
    WriteClaims = Annotated[SessionClaims, Depends(write_access)]

    @app.exception_handler(AuthenticationError)
    async def authentication_error(request: Request, _error: AuthenticationError):
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="authentication_required",
            title="Authentication required",
        )

    @app.exception_handler(OriginRejectedError)
    async def origin_error(request: Request, _error: OriginRejectedError):
        return _problem(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="origin_rejected",
            title="Origin rejected",
        )

    @app.exception_handler(CsrfRejectedError)
    async def csrf_error(request: Request, _error: CsrfRejectedError):
        return _problem(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="csrf_rejected",
            title="CSRF validation failed",
        )

    @app.exception_handler(AccessDeniedError)
    async def access_error(request: Request, _error: AccessDeniedError):
        return _problem(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="forbidden",
            title="Access forbidden",
        )

    @app.exception_handler(ResourceNotFoundError)
    @app.exception_handler(FileNotFoundError)
    async def not_found_error(request: Request, _error: Exception):
        return _problem(
            request,
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            title="Resource not found",
        )

    @app.exception_handler(TurnConflictError)
    async def conflict_error(request: Request, error: TurnConflictError):
        return _problem(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="turn_conflict",
            title="Session already has an active turn",
            detail=str(error),
        )

    @app.exception_handler(GatewayNotStartedError)
    async def gateway_error(request: Request, _error: GatewayNotStartedError):
        return _problem(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="gateway_unavailable",
            title="Backend Gateway is not ready",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return _problem(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            title="Request validation failed",
            detail=str(error.errors()),
        )

    @app.get("/health/live", tags=["health"])
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready(request: Request):
        health = await request.app.state.gateway.health()
        ready = health.started and health.accepting_turns and health.status == "ok"
        return JSONResponse(
            {
                "status": "ready" if ready else "not_ready",
                "active_turns": health.active_turns,
                "durable_events": health.durable_events,
            },
            status_code=200 if ready else 503,
        )

    @app.post("/api/v1/auth/session", status_code=status.HTTP_201_CREATED, tags=["auth"])
    async def create_auth_session(request: Request, response: Response):
        auth.require_same_origin(request.headers.get("origin"), request.headers.get("host"))
        token, claims = auth.issue()
        response.set_cookie(
            auth.cookie_name,
            token,
            max_age=auth.ttl_s,
            httponly=True,
            secure=auth.secure,
            samesite="strict",
            path="/",
        )
        return {
            "user_id": claims.user_id,
            "workspace_ids": sorted(claims.workspace_ids),
            "csrf_token": claims.csrf_token,
            "expires_at": claims.expires_at,
            "ephemeral_secret": auth.ephemeral_secret,
        }

    @app.get("/api/v1/auth/session", tags=["auth"])
    async def get_auth_session(claims: Annotated[SessionClaims, Depends(current_claims)]):
        return {
            "user_id": claims.user_id,
            "workspace_ids": sorted(claims.workspace_ids),
            "csrf_token": claims.csrf_token,
            "expires_at": claims.expires_at,
        }

    @app.delete("/api/v1/auth/session", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
    async def delete_auth_session(response: Response, _claims: WriteClaims):
        response.delete_cookie(auth.cookie_name, path="/", samesite="strict")

    @app.get("/api/v1/sessions", tags=["sessions"])
    async def list_sessions(request: Request, principal: Principal):
        return {"items": await request.app.state.gateway.sessions.list(principal)}

    @app.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED, tags=["sessions"])
    async def create_session(
        body: CreateSessionBody,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        session = await request.app.state.gateway.create_session(
            principal,
            workspace_id=body.workspace_id,
            channel="web",
        )
        await hub.broadcast(
            control_event(
                "session.created",
                session_id=session.session_id,
                payload={"workspace_id": session.workspace_id},
            ),
            user_id=principal.user_id,
        )
        return session.model_dump(mode="json")

    @app.get("/api/v1/sessions/{session_id}", tags=["sessions"])
    async def get_session(session_id: str, request: Request, principal: Principal):
        context = await request.app.state.gateway.sessions.resolve(principal, session_id)
        return context.model_dump(mode="json")

    @app.get("/api/v1/sessions/{session_id}/messages", tags=["sessions"])
    async def get_messages(session_id: str, request: Request, principal: Principal):
        return {
            "items": await request.app.state.gateway.sessions.messages(principal, session_id)
        }

    @app.get("/api/v1/sessions/{session_id}/turns", tags=["sessions"])
    async def list_turns(
        session_id: str,
        request: Request,
        principal: Principal,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        turns = await request.app.state.gateway.list_turns(
            principal,
            session_id,
            limit=limit,
        )
        return {"items": [turn.model_dump(mode="json") for turn in turns]}

    @app.delete("/api/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["sessions"])
    async def delete_session(
        session_id: str,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        await request.app.state.gateway.delete_session(principal, session_id)
        await hub.broadcast(
            control_event("session.deleted", session_id=session_id),
            user_id=principal.user_id,
        )

    @app.post("/api/v1/chat/turns", status_code=status.HTTP_202_ACCEPTED, tags=["chat"])
    async def submit_turn(
        body: SubmitChatBody,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        accepted = await request.app.state.gateway.submit_turn(
            principal,
            SubmitTurnRequest(**body.model_dump()),
        )
        return accepted.model_dump(mode="json")

    @app.get("/api/v1/chat/turns/{turn_id}", tags=["chat"])
    async def get_turn(turn_id: str, request: Request, principal: Principal):
        turn = await request.app.state.gateway.get_turn(principal, turn_id)
        return turn.model_dump(mode="json")

    @app.get("/api/v1/chat/turns/{turn_id}/events", tags=["chat"])
    async def replay_turn_events(
        turn_id: str,
        request: Request,
        principal: Principal,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=2_000),
    ):
        events = await request.app.state.gateway.replay_events(
            principal,
            turn_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        return {"items": [event.model_dump(mode="json") for event in events]}

    @app.post("/api/v1/chat/turns/{turn_id}/cancel", tags=["chat"])
    async def cancel_turn(
        turn_id: str,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        turn = await request.app.state.gateway.cancel_turn(principal, turn_id)
        return turn.model_dump(mode="json")

    @app.post("/api/v1/chat/injections", status_code=status.HTTP_202_ACCEPTED, tags=["chat"])
    async def inject_message(
        body: InjectChatBody,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        accepted = await request.app.state.gateway.inject_message(
            principal,
            InjectMessageRequest(**body.model_dump()),
        )
        return accepted.model_dump(mode="json")

    @app.post("/api/v1/tool-approvals", status_code=status.HTTP_201_CREATED, tags=["tools"])
    async def approve_tool(
        body: ToolApprovalBody,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        return await request.app.state.gateway.grant_high_risk_tool(
            principal,
            **body.model_dump(),
        )

    @app.get("/api/v1/settings", tags=["settings"])
    async def get_settings(request: Request, principal: Principal):
        preferences = await request.app.state.gateway.get_user_settings(principal)
        return {"preferences": preferences, "runtime": _public_runtime_settings()}

    @app.get("/api/v1/protocol", tags=["runtime"])
    async def get_protocol(_principal: Principal):
        return {
            "version": "1",
            "websocket_path": "/ws/v1",
            "commands": [
                "chat.send",
                "chat.inject",
                "chat.cancel",
                "session.subscribe",
                "session.unsubscribe",
                "stream.resume",
                "ping",
            ],
            "events": [
                "connection.ready",
                "command.ack",
                "command.error",
                "chat.accepted",
                "chat.started",
                "chat.delta",
                "chat.reasoning.delta",
                "chat.message.completed",
                "chat.completed",
                "chat.error",
                "chat.cancelled",
                "tool.started",
                "tool.progress",
                "tool.completed",
                "tool.error",
                "worker.started",
                "worker.progress",
                "worker.completed",
                "worker.error",
                "session.created",
                "session.updated",
                "session.deleted",
                "settings.updated",
                "stream.gap",
                "pong",
                "server.shutdown",
            ],
            "limits": {
                "max_websocket_message_bytes": max_ws_message_bytes,
                "websocket_send_queue_size": ws_send_queue_size,
                "websocket_send_timeout_s": ws_send_timeout_s,
            },
        }

    @app.patch("/api/v1/settings", tags=["settings"])
    async def update_settings(
        body: UpdateSettingsBody,
        request: Request,
        principal: Principal,
        _claims: WriteClaims,
    ):
        changes = body.model_dump(exclude_none=True)
        if "default_workspace_id" in changes:
            principal.require_workspace(changes["default_workspace_id"])
        updated = await request.app.state.gateway.update_user_settings(principal, changes)
        await hub.broadcast(
            control_event("settings.updated", payload=updated),
            user_id=principal.user_id,
        )
        return updated

    @app.websocket("/ws/v1")
    async def websocket_route(websocket: WebSocket):
        await websocket_endpoint(
            websocket,
            gateway=websocket.app.state.gateway,
            auth=auth,
            hub=hub,
            max_message_bytes=max_ws_message_bytes,
            max_queue=stream_queue_size,
            send_queue_size=ws_send_queue_size,
            send_timeout_s=ws_send_timeout_s,
        )

    static_dir_value = str(web_config.get("static_dir", "")).strip()
    static_dir = Path(static_dir_value).expanduser() if static_dir_value else None
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="webui")
    else:
        @app.get("/", include_in_schema=False)
        async def api_root():
            return {
                "name": "NLP Agent Backend",
                "api": "/api/v1",
                "websocket": "/ws/v1",
                "docs": "/api/docs",
            }

    return app


app = create_app()
