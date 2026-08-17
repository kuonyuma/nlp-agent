"""FastAPI auth dependencies for the user/workspace/classroom_join modules.

Bridges the vertical modules with V3's existing ``SameOriginSessionAuth``
(``server/web/auth.py``), mirroring the closures inside ``create_app`` so the
new module controllers enforce the same authentication + CSRF + same-origin
checks as the rest of the API.

Exports:
  - get_db_session: AsyncSession dependency from the gateway's session factory
  - get_current_principal: cookie auth + RBAC principal resolution
  - get_write_access: CSRF + origin validation for state-changing requests
  - Principal / WriteClaims: Annotated type aliases for controller use
"""

from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Depends, Header, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from core.identity import AuthenticatedPrincipal
from server.rbac.service import rbac_service
from server.web.auth import (
    AuthenticationError,
    CsrfRejectedError,
    OriginRejectedError,
    SameOriginSessionAuth,
    SessionClaims,
)


def _claims(request: Request) -> SessionClaims:
    """Authenticate the session cookie; raises AuthenticationError on failure."""
    auth: SameOriginSessionAuth = request.app.state.auth
    token = request.cookies.get(auth.cookie_name)
    return auth.authenticate(token)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async database session from the gateway's session factory."""
    factory = getattr(request.app.state.gateway, "authorization_session_factory", None)
    if factory is None:
        raise RuntimeError("RBAC persistence requires MySQL")
    async with factory() as session:
        yield session


async def get_current_principal(
    request: Request,
    claims: Annotated[SessionClaims, Depends(_claims)],
) -> AuthenticatedPrincipal:
    """Resolve roles/workspace/ classroom membership from MySQL.

    Mirrors ``resolve_principal`` in ``server/web/app.py``: guests get a
    lightweight principal, everyone else is reloaded from ``nlp_users`` by
    username (the signed session carries the username as ``user_id``).
    """
    if claims.roles == frozenset({"guest"}):
        return claims.principal()
    factory = getattr(request.app.state.gateway, "authorization_session_factory", None)
    if factory is None:
        return claims.principal()
    async with factory() as session:
        return await rbac_service.principal_for_username(session, claims.user_id)


async def get_write_access(
    request: Request,
    claims: Annotated[SessionClaims, Depends(_claims)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> SessionClaims:
    """Validate CSRF token and same-origin for state-changing requests."""
    auth: SameOriginSessionAuth = request.app.state.auth
    auth.require_same_origin(request.headers.get("origin"), request.headers.get("host"))
    auth.require_csrf(claims, csrf_token)
    return claims


Principal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]
WriteClaims = Annotated[SessionClaims, Depends(get_write_access)]
