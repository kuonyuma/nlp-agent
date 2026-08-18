"""Security-hardening regression tests (阶段3 / P0 closure).

Covers the cross-resource failure paths required by review §10:

- P0-4: workspace member changes are object-scoped — a manager of workspace A
  cannot mutate workspace B's membership, even though the capability
  (``CLASSROOM_MEMBER_MANAGE``) is identical. Enforced by
  ``authorization_service.require(..., workspace_id=...)``.
- P0-5: classroom join approval/rejection bind ``request_id`` to ``class_id`` at
  the service layer, so a request belonging to class A cannot be approved via
  class B (the IDOR that the path-level classroom permission alone would miss).
- Capability gate: account disable/enable is a high-risk action gated by
  ``SYSTEM_USER_MANAGE`` and must reject lower-privilege roles (teacher).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.rbac import Permission, authorization_service
from server.classroom_join import service as classroom_join_service
from server.infrastructure.mysql import DatabaseConfig, create_engine, create_session_factory
from server.infrastructure.mysql.models import (
    ClassJoinRequestModel,
    ClassroomModel,
    UserModel,
    WorkspaceModel,
)


def _principal(*, user_id: str = "u-1", workspaces=("ws-a",), roles=("teacher",)) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        workspace_ids=frozenset(workspaces),
        roles=frozenset(roles),
    )


def test_workspace_member_change_is_object_scoped_not_role_wide() -> None:
    """P0-4: 拥有 CLASSROOM_MEMBER_MANAGE 也只能作用于自己所属的 workspace。"""
    principal = _principal()
    # 对自己所属的 ws-a 放行
    authorization_service.require(principal, Permission.CLASSROOM_MEMBER_MANAGE, workspace_id="ws-a")
    # 对其它 workspace 必须被拒（对象级 IDOR 防护）
    with pytest.raises(AccessDeniedError):
        authorization_service.require(
            principal, Permission.CLASSROOM_MEMBER_MANAGE, workspace_id="ws-b"
        )


def test_user_disable_requires_system_user_manage_not_teacher() -> None:
    """账号停用是高危操作，仅 SYSTEM_USER_MANAGE 可放行（非 teacher）。"""
    teacher = _principal(roles=("teacher",))
    with pytest.raises(AccessDeniedError):
        authorization_service.require(teacher, Permission.SYSTEM_USER_MANAGE)
    admin = _principal(roles=("admin",))
    authorization_service.require(admin, Permission.SYSTEM_USER_MANAGE)


@pytest.fixture
async def mysql_session_factory():
    database_url = os.getenv("NLP_AGENT_DATABASE_URL")
    if not database_url:
        pytest.skip("MySQL integration database is not configured")
    engine = create_engine(DatabaseConfig(database_url))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_classroom_approve_rejects_cross_class_request_id(mysql_session_factory) -> None:
    """P0-5 核心：approve 时 request_id 必须与 class_id 绑定，跨班提交返回 None（→ 404）。"""
    async with mysql_session_factory() as session:
        workspace_id = str(uuid4())
        class_a = str(uuid4())
        class_b = str(uuid4())
        user_id = str(uuid4())
        req_id = str(uuid4())

        session.add(
            WorkspaceModel(id=workspace_id, slug=f"ws-{uuid4().hex[:8]}", name="WS", status="active")
        )
        session.add(
            ClassroomModel(id=class_a, workspace_id=workspace_id, name="Class A", status="active")
        )
        session.add(
            ClassroomModel(id=class_b, workspace_id=workspace_id, name="Class B", status="active")
        )
        session.add(
            UserModel(
                id=user_id,
                username=f"joiner-{uuid4().hex[:8]}",
                password_hash="not-used",
                display_name="Joiner",
            )
        )
        session.add(
            ClassJoinRequestModel(id=req_id, class_id=class_a, user_id=user_id, status="pending")
        )
        await session.commit()

        # 用 class_b 去审批属于 class_a 的请求 → 必须命中不到（IDOR 防护）
        cross = await classroom_join_service.approve_join_request(
            session, req_id, class_b, reviewed_by="reviewer"
        )
        assert cross is None

        # 用正确的 class_a 去审批 → 命中
        ok = await classroom_join_service.approve_join_request(
            session, req_id, class_a, reviewed_by="reviewer"
        )
        assert ok is not None
        assert ok.id == req_id
        assert ok.status == "approved"
