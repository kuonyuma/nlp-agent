"""I/O-free collection of authorization decisions at transport boundaries."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from core.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    actor_user_id: str
    decision: str
    permission_code: str
    resource_type: str | None = None
    resource_id: str | None = None
    workspace_id: str | None = None


_decisions: ContextVar[list[AuthorizationDecision] | None] = ContextVar(
    "authorization_decisions", default=None
)


def begin() -> tuple[Token[list[AuthorizationDecision] | None], list[AuthorizationDecision]]:
    collected: list[AuthorizationDecision] = []
    return _decisions.set(collected), collected


def end(token: Token[list[AuthorizationDecision] | None]) -> None:
    _decisions.reset(token)


def record(
    principal: AuthenticatedPrincipal, *, decision: str, permission_code: str,
    resource_type: str | None = None, resource_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    collected = _decisions.get()
    if collected is not None:
        collected.append(AuthorizationDecision(
            actor_user_id=principal.user_id, decision=decision,
            permission_code=permission_code, resource_type=resource_type,
            resource_id=resource_id, workspace_id=workspace_id,
        ))
