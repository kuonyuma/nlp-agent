"""Opt-in MySQL + Docker reconciliation proof used by the Linux CI gate."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SANDBOX_DOCKER_MANAGER_INTEGRATION") != "1",
    reason="Docker manager integration is enabled in CI only",
)
DOCKER_COMMAND_TIMEOUT_SECONDS = 120


@pytest.mark.asyncio
async def test_manager_destroys_unregistered_managed_container() -> None:
    from server.infrastructure.mysql import DatabaseConfig, create_engine, create_session_factory
    from server.sandbox.docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig
    from server.sandbox.manager import WarmPoolManager

    name = f"nova-manager-orphan-{uuid4().hex}"
    subprocess.run(
        ["docker", "run", "--detach", "--name", name, "--label", "nova.sandbox.managed=true", "alpine:3.20", "sleep", "300"],
        check=True, capture_output=True, text=True, timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
    )
    engine = create_engine(DatabaseConfig(os.environ["NLP_AGENT_DATABASE_URL"], pool_size=1, max_overflow=0))
    try:
        manager = WarmPoolManager(
            session_factory=create_session_factory(engine),
            docker=DockerRuntimeAdapter(DockerRuntimeConfig(image="alpine@sha256:" + "0" * 64)),
            resource_profile_id="python-base",
            ready_target=0,
        )
        actions = await manager.reconcile()
        assert name in actions.destroy_orphans
        remaining = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=30)
        assert remaining.returncode != 0
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, text=True, timeout=30)
        await engine.dispose()


@pytest.mark.asyncio
async def test_manager_destroys_runtime_when_auth_session_is_revoked() -> None:
    from sqlalchemy import select

    from server.infrastructure.mysql import DatabaseConfig, create_engine, create_session_factory
    from server.infrastructure.mysql.models import (
        SandboxEnvironmentModel, SandboxLeaseModel, SandboxRuntimeInstanceModel, SessionModel, WorkspaceMemberModel,
    )
    from server.sandbox.docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig
    from server.sandbox.manager import WarmPoolManager
    from server.user.schemas import UserCreate
    from server.user.service import UserService

    name = f"nova-manager-revoked-{uuid4().hex}"
    subprocess.run(
        ["docker", "run", "--detach", "--name", name, "--label", "nova.sandbox.managed=true", "alpine:3.20", "sleep", "300"],
        check=True, capture_output=True, text=True, timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
    )
    engine = create_engine(DatabaseConfig(os.environ["NLP_AGENT_DATABASE_URL"], pool_size=1, max_overflow=0))
    factory = create_session_factory(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        async with factory.begin() as session:
            user = await UserService(session).create_user(
                UserCreate(username=f"reconcile{uuid4().hex[:10]}", display_name="Reconcile", password="InitialPw0rd1")
            )
            workspace_id = await session.scalar(select(WorkspaceMemberModel.workspace_id).where(WorkspaceMemberModel.user_id == user.id))
            session_id = str(uuid4())
            environment_id = str(uuid4())
            runtime_id = str(uuid4())
            session.add(SessionModel(
                id=session_id, user_id=user.id, workspace_id=workspace_id,
                token_hash=f"token-{session_id}", csrf_hash=f"csrf-{session_id}",
                authorization_version=user.authorization_version, expires_at=now + timedelta(hours=1),
                revoked_at=now,
            ))
            session.add(SandboxEnvironmentModel(id=environment_id, owner_user_id=user.id, generation=1))
            session.add(SandboxRuntimeInstanceModel(
                id=runtime_id, environment_id=environment_id, external_runtime_id=name,
                runtime_kind="docker", state="assigned", generation=1,
            ))
            await session.flush()
            session.add(SandboxLeaseModel(
                id=str(uuid4()), environment_id=environment_id, user_id=user.id,
                auth_session_id=session_id, runtime_instance_id=runtime_id, workspace_id=workspace_id,
                generation=1, state="active", expires_at=now + timedelta(hours=1),
            ))
        manager = WarmPoolManager(
            session_factory=factory,
            docker=DockerRuntimeAdapter(DockerRuntimeConfig(image="alpine@sha256:" + "0" * 64)),
            resource_profile_id="python-base",
            ready_target=0,
        )
        actions = await manager.reconcile()
        assert name not in actions.destroy_orphans
        remaining = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=30)
        assert remaining.returncode != 0
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, text=True, timeout=30)
        await engine.dispose()
