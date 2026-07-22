"""Authorization helpers shared by read and write developer routes."""

from core.identity import AccessDeniedError, AuthenticatedPrincipal


def require_admin(principal: AuthenticatedPrincipal) -> None:
    if not principal.is_admin:
        raise AccessDeniedError("administrator role is required")
