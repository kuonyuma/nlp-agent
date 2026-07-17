"""Authenticated identity contracts shared by Gateway-facing services."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.session_context import SessionContext


class AccessDeniedError(PermissionError):
    """Raised when an authenticated principal does not own a resource."""


class AuthenticatedPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    workspace_ids: frozenset[str] = Field(default_factory=lambda: frozenset({"default"}))
    roles: frozenset[str] = Field(default_factory=frozenset)

    @classmethod
    def system_admin(cls) -> "AuthenticatedPrincipal":
        return cls(user_id="system", workspace_ids=frozenset({"*"}), roles=frozenset({"admin"}))

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def can_access(self, context: SessionContext) -> bool:
        return self.is_admin or (
            self.user_id == context.user_id
            and ("*" in self.workspace_ids or context.workspace_id in self.workspace_ids)
        )

    def require_context(self, context: SessionContext) -> None:
        if not self.can_access(context):
            raise AccessDeniedError(
                f"principal {self.user_id!r} cannot access session {context.session_id!r}"
            )

    def require_workspace(self, workspace_id: str) -> None:
        if not self.is_admin and "*" not in self.workspace_ids and workspace_id not in self.workspace_ids:
            raise AccessDeniedError(
                f"principal {self.user_id!r} cannot access workspace {workspace_id!r}"
            )
