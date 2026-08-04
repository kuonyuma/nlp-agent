"""Application service for the MySQL role assignment source of truth."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.identity import AuthenticatedPrincipal
from server.infrastructure.mysql.models import (
    RoleModel,
    UserModel,
    UserRoleModel,
    WorkspaceMemberModel,
)


class UnknownRoleError(ValueError):
    pass


class RbacService:
    async def principal_for_username(
        self, session: AsyncSession, username: str
    ) -> AuthenticatedPrincipal:
        """Resolve the authoritative runtime principal from MySQL.

        The signed browser session proves who authenticated; role and workspace
        membership are deliberately reloaded here so a changed assignment takes
        effect on the next HTTP request (and on WebSocket guard ticks).
        """
        user = await session.scalar(
            select(UserModel).where(UserModel.username == username, UserModel.status == "active")
        )
        if user is None:
            raise PermissionError("authenticated user is not active in RBAC")
        roles = await self.roles_for(session, user.id)
        workspace_ids = frozenset(
            (
                await session.scalars(
                    select(WorkspaceMemberModel.workspace_id).where(
                        WorkspaceMemberModel.user_id == user.id,
                        WorkspaceMemberModel.status == "active",
                    )
                )
            ).all()
        )
        return AuthenticatedPrincipal(
            user_id=user.id,
            workspace_ids=workspace_ids,
            roles=roles,
            authorization_version=user.authorization_version,
        )
    async def roles_for(self, session: AsyncSession, user_id: str) -> frozenset[str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await session.execute(
            select(RoleModel.code)
            .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
            .where(
                UserRoleModel.user_id == user_id,
                RoleModel.status == "active",
                (UserRoleModel.expires_at.is_(None)) | (UserRoleModel.expires_at > now),
            )
        )
        return frozenset(result.scalars())

    async def replace_user_roles(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        role_codes: set[str] | frozenset[str],
        assigned_by_user_id: str | None,
    ) -> frozenset[str]:
        user = await session.scalar(
            select(UserModel).where(UserModel.id == user_id).with_for_update()
        )
        if user is None:
            raise KeyError(user_id)
        roles = list(
            (
                await session.scalars(
                    select(RoleModel).where(
                        RoleModel.code.in_(role_codes), RoleModel.status == "active"
                    )
                )
            ).all()
        )
        found_codes = {role.code for role in roles}
        if found_codes != set(role_codes):
            missing = ", ".join(sorted(set(role_codes) - found_codes))
            raise UnknownRoleError(f"unknown or inactive role codes: {missing}")
        await session.execute(delete(UserRoleModel).where(UserRoleModel.user_id == user_id))
        session.add_all(
            [
                UserRoleModel(
                    user_id=user_id,
                    role_id=role.id,
                    assigned_by_user_id=assigned_by_user_id,
                )
                for role in roles
            ]
        )
        user.authorization_version += 1
        await session.flush()
        return frozenset(found_codes)


rbac_service = RbacService()
