"""Application service for the MySQL role assignment source of truth."""

from __future__ import annotations

from datetime import datetime, timezone

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.identity import AuthenticatedPrincipal
from server.infrastructure.mysql.models import (
    RoleModel,
    PermissionModel,
    UserModel,
    UserRoleModel,
    WorkspaceMemberModel,
    AuthorizationAuditLogModel,
    RolePermissionModel,
    RolePermissionScopeModel,
)


class UnknownRoleError(ValueError):
    pass


class RbacService:
    async def principal_for_user_id(
        self, session: AsyncSession, user_id: str
    ) -> AuthenticatedPrincipal:
        user = await session.scalar(
            select(UserModel).where(UserModel.id == user_id, UserModel.status == "active")
        )
        if user is None:
            raise PermissionError("turn submitter is not active in RBAC")
        roles = await self.roles_for(session, user.id)
        permissions = frozenset(
            (
                await session.scalars(
                    select(PermissionModel.code)
                    .join(RolePermissionModel, RolePermissionModel.permission_id == PermissionModel.id)
                    .join(UserRoleModel, UserRoleModel.role_id == RolePermissionModel.role_id)
                    .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(
                        UserRoleModel.user_id == user.id,
                        RoleModel.status == "active",
                        PermissionModel.status == "active",
                    )
                )
            ).all()
        )
        scope_rows = await session.execute(
            select(PermissionModel.code, RolePermissionScopeModel.scope_type)
            .join(RolePermissionScopeModel, RolePermissionScopeModel.permission_id == PermissionModel.id)
            .join(UserRoleModel, UserRoleModel.role_id == RolePermissionScopeModel.role_id)
            .where(UserRoleModel.user_id == user.id, PermissionModel.status == "active")
        )
        permission_scopes: dict[str, frozenset[str]] = {}
        for code, scope in scope_rows:
            permission_scopes[code] = permission_scopes.get(code, frozenset()) | {scope}
        workspaces = frozenset(
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
            workspace_ids=workspaces,
            roles=roles,
            permissions=permissions,
            permission_scopes=permission_scopes,
            authorization_version=user.authorization_version,
        )

    async def principal_for_username(
        self, session: AsyncSession, username: str
    ) -> AuthenticatedPrincipal:
        """Resolve the authoritative runtime principal from MySQL.

        The signed browser session proves who authenticated; role and workspace
        membership are deliberately reloaded here so a changed assignment takes
        effect on the next HTTP request (and on WebSocket guard ticks).
        """
        user = await session.scalar(select(UserModel).where(UserModel.username == username))
        if user is None:
            raise PermissionError("authenticated user is not active in RBAC")
        return await self.principal_for_user_id(session, user.id)

    async def role_catalog(self, session: AsyncSession) -> list[RoleModel]:
        return list((await session.scalars(select(RoleModel).order_by(RoleModel.code))).all())

    async def permission_catalog(self, session: AsyncSession) -> list[PermissionModel]:
        return list((await session.scalars(select(PermissionModel).order_by(PermissionModel.code))).all())

    async def audit(
        self,
        session: AsyncSession,
        *,
        actor_user_id: str | None,
        target_user_id: str | None,
        decision: str,
        reason_code: str,
        permission_code: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        session.add(
            AuthorizationAuditLogModel(
                id=str(uuid.uuid4()), actor_user_id=actor_user_id,
                target_user_id=target_user_id, decision=decision,
                reason_code=reason_code, permission_code=permission_code,
                resource_type=resource_type, resource_id=resource_id,
                detail_json=detail or {},
            )
        )

    async def audit_records(
        self, session: AsyncSession, *, limit: int = 100, actor_user_id: str | None = None
    ) -> list[AuthorizationAuditLogModel]:
        statement = select(AuthorizationAuditLogModel).order_by(
            AuthorizationAuditLogModel.created_at.desc()
        ).limit(max(1, min(limit, 500)))
        if actor_user_id is not None:
            statement = statement.where(AuthorizationAuditLogModel.actor_user_id == actor_user_id)
        return list((await session.scalars(statement)).all())

    async def user_role_codes(self, session: AsyncSession, user_id: str) -> frozenset[str]:
        user = await session.scalar(select(UserModel.id).where(UserModel.id == user_id))
        if user is None:
            raise KeyError(user_id)
        return await self.roles_for(session, user_id)
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
        if user_id == assigned_by_user_id and not set(role_codes).issubset(
            await self.roles_for(session, user_id)
        ):
            raise PermissionError("users cannot grant themselves additional roles")
        current_roles = await self.roles_for(session, user_id)
        if "developer" in current_roles and "developer" not in found_codes:
            developer_count = await session.scalar(
                select(func.count(UserRoleModel.user_id))
                .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                .where(RoleModel.code == "developer", RoleModel.status == "active")
            )
            if int(developer_count or 0) <= 1:
                raise PermissionError("cannot remove the last active developer")
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
        await self.audit(
            session,
            actor_user_id=assigned_by_user_id,
            target_user_id=user_id,
            decision="allow",
            reason_code="user_roles_replaced",
            permission_code="system:role:manage",
            resource_type="user",
            resource_id=user_id,
            detail={"before": sorted(current_roles), "after": sorted(found_codes)},
        )
        await session.flush()
        return frozenset(found_codes)


rbac_service = RbacService()
