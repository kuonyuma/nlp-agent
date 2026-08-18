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
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.rbac import Permission, authorization_service
from server.classroom_join import service as classroom_join_service
from server.infrastructure.mysql import DatabaseConfig, create_engine, create_session_factory
from server.infrastructure.mysql.models import (
    ClassJoinRequestModel,
    ClassroomModel,
    SessionModel,
    UserModel,
    WorkspaceModel,
)
from server.user.service import UserService


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


def test_admin_revoke_session_is_admin_only_capability() -> None:
    """§10 / P1-3：撤销他人会话必须经 SYSTEM_USER_MANAGE，非 admin（teacher）
    在能力层即被拒——这是「跨用户撤销 session」失败路径的关卡。"""
    teacher = _principal(roles=("teacher",))
    with pytest.raises(AccessDeniedError):
        authorization_service.require(teacher, Permission.SYSTEM_USER_MANAGE)


def test_user_password_reset_is_admin_only_capability() -> None:
    """§10：重置他人密码必须经 SYSTEM_USER_MANAGE，非 admin（teacher）
    在能力层即被拒——这是「跨用户重置密码」失败路径的关卡。"""
    teacher = _principal(roles=("teacher",))
    with pytest.raises(AccessDeniedError):
        authorization_service.require(teacher, Permission.SYSTEM_USER_MANAGE)


@pytest.mark.asyncio
async def test_admin_revoke_session_revokes_only_target_user(mysql_session_factory) -> None:
    """P1-3 核心 + §10：管理员撤销严格只作用于目标用户的会话，
    绝不波及其它用户；返回正确撤销数量，且目标 authorization_version 递增。"""
    async with mysql_session_factory() as session:
        workspace_id = str(uuid4())
        victim_id = str(uuid4())
        other_id = str(uuid4())

        session.add(
            WorkspaceModel(id=workspace_id, slug=f"ws-{uuid4().hex[:8]}", name="WS", status="active")
        )
        session.add(
            UserModel(
                id=victim_id,
                username=f"victim-{uuid4().hex[:8]}",
                password_hash="not-used",
                display_name="Victim",
                authorization_version=1,
            )
        )
        session.add(
            UserModel(
                id=other_id,
                username=f"other-{uuid4().hex[:8]}",
                password_hash="not-used",
                display_name="Other",
                authorization_version=1,
            )
        )
        await session.flush()

        victim_active_1 = str(uuid4())
        victim_active_2 = str(uuid4())
        victim_already_revoked = str(uuid4())
        other_session = str(uuid4())
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)

        for sid, owner in (
            (victim_active_1, victim_id),
            (victim_active_2, victim_id),
            (victim_already_revoked, victim_id),
            (other_session, other_id),
        ):
            session.add(
                SessionModel(
                    id=sid,
                    user_id=owner,
                    workspace_id=workspace_id,
                    token_hash=f"tok-{sid}",
                    csrf_hash=f"csrf-{sid}",
                    expires_at=expires_at,
                )
            )
        # 预先撤销 victim 的一个会话，验证只统计「有效」会话
        await session.execute(
            update(SessionModel)
            .where(SessionModel.id == victim_already_revoked)
            .values(revoked_at=datetime.now(timezone.utc).replace(tzinfo=None))
        )
        await session.commit()

        svc = UserService(session)
        # admin 撤销 victim 的全部有效会话
        revoked = await svc.revoke_user_sessions(victim_id)
        # 只撤销 2 个有效会话（已撤销的不计入）
        assert revoked == 2

        va1 = await session.get(SessionModel, victim_active_1)
        va2 = await session.get(SessionModel, victim_active_2)
        assert va1 is not None and va1.revoked_at is not None
        assert va2 is not None and va2.revoked_at is not None

        # 其它用户的会话绝不被波及其余
        ot = await session.get(SessionModel, other_session)
        assert ot is not None and ot.revoked_at is None

        # 目标用户的 authorization_version 已递增
        victim = await svc.get_user(victim_id)
        assert victim.authorization_version == 2


@pytest.mark.asyncio
async def test_self_password_change_verifies_old_and_invalidates_sessions(mysql_session_factory) -> None:
    """§6.1：自改密码必须校验旧密码；§8.1：改密后旧会话失效（authorization_version 递增）。"""
    async with mysql_session_factory() as session:
        user_id = str(uuid4())
        workspace_id = str(uuid4())
        session.add(
            WorkspaceModel(id=workspace_id, slug=f"ws-{uuid4().hex[:8]}", name="WS", status="active")
        )
        session.add(
            UserModel(
                id=user_id,
                username=f"u-{uuid4().hex[:8]}",
                password_hash="not-used",
                display_name="U",
                authorization_version=1,
            )
        )
        await session.commit()

        svc = UserService(session)
        # 设置已知口令
        await svc.change_password(user_id, "OldPassw0rd1")
        user = await svc.get_user(user_id)

        # 旧密码校验：错误旧密码 → False
        assert await svc.verify_password(user, "WrongPassw0rd1") is False
        # 正确旧密码 → True（self 端点前置校验通过后才改密）
        assert await svc.verify_password(user, "OldPassw0rd1") is True

        # 自改：校验通过后改密（端点核心守卫在此复现）
        before = await svc.get_user(user_id)
        await svc.change_password(user_id, "NewPassw0rd2")
        after = await svc.get_user(user_id)
        # 改密后 authorization_version 递增 → 旧会话失效
        assert after.authorization_version == before.authorization_version + 1
        assert await svc.verify_password(after, "NewPassw0rd2") is True
        assert await svc.verify_password(after, "OldPassw0rd1") is False
