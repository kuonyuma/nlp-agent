"""Opt-in MySQL + Docker reconciliation proof used by the Linux CI gate."""

from __future__ import annotations

import os
import subprocess
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SANDBOX_DOCKER_MANAGER_INTEGRATION") != "1",
    reason="Docker manager integration is enabled in CI only",
)


@pytest.mark.asyncio
async def test_manager_destroys_unregistered_managed_container() -> None:
    from server.infrastructure.mysql import DatabaseConfig, create_engine, create_session_factory
    from server.sandbox.docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig
    from server.sandbox.manager import WarmPoolManager

    name = f"nova-manager-orphan-{uuid4().hex}"
    subprocess.run(
        ["docker", "run", "--detach", "--name", name, "--label", "nova.sandbox.managed=true", "alpine:3.20", "sleep", "300"],
        check=True, capture_output=True, text=True,
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
        remaining = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
        assert remaining.returncode != 0
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, text=True)
        await engine.dispose()
