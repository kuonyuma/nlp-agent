"""Authorization helpers shared by read and write developer routes."""

from core.identity import AuthenticatedPrincipal
from core.rbac import Permission, authorization_service


def require_admin(principal: AuthenticatedPrincipal) -> None:
    """Compatibility name for the system RBAC management capability.

    Existing routes retain this helper while the public role changes from the
    old ``admin`` claim to the design's ``developer`` role.
    """

    authorization_service.require(principal, Permission.SYSTEM_ROLE_MANAGE)
