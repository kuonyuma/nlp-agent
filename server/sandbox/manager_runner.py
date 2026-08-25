"""Dedicated Process entry point for Phase 2 Sandbox Manager.

Run this separately from the Web service.  Only this process is granted Docker
Engine access; its runtime image must be pinned to a digest.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from configs.settings import settings
from server.infrastructure.mysql.config import DatabaseConfig
from server.infrastructure.mysql.engine import create_engine, create_session_factory

from .commands import create_sandbox_manager_command_store
from .docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig
from .manager import WarmPoolManager
from .optimization import AdaptivePoolPolicy
from .metrics import create_sandbox_adaptive_state_store, create_sandbox_metrics_store


async def run_forever() -> None:
    image = settings.NLP_AGENT_SANDBOX_DOCKER_IMAGE_DIGEST.strip()
    target = settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_TARGET
    if not image or target <= 0:
        raise RuntimeError(
            "Set NLP_AGENT_SANDBOX_DOCKER_IMAGE_DIGEST and a positive "
            "NLP_AGENT_SANDBOX_WARM_POOL_READY_TARGET before starting Sandbox Manager."
        )
    engine = create_engine(DatabaseConfig.from_runtime(settings.database_runtime))
    adaptive_state_store = (
        create_sandbox_adaptive_state_store()
        if settings.NLP_AGENT_SANDBOX_ADAPTIVE_POOL_ENABLED
        else None
    )
    metrics_store = create_sandbox_metrics_store() if settings.NLP_AGENT_SANDBOX_ADAPTIVE_POOL_ENABLED else None
    manager = WarmPoolManager(
        session_factory=create_session_factory(engine),
        docker=DockerRuntimeAdapter(DockerRuntimeConfig(image=image)),
        resource_profile_id="python-base",
        ready_target=target,
        adaptive_policy=(
            AdaptivePoolPolicy(
                ready_min=settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_MIN,
                ready_max=settings.NLP_AGENT_SANDBOX_WARM_POOL_READY_MAX,
                burst_buffer=settings.NLP_AGENT_SANDBOX_BURST_BUFFER,
            )
            if settings.NLP_AGENT_SANDBOX_ADAPTIVE_POOL_ENABLED
            else None
        ),
        adaptive_state_store=adaptive_state_store,
        metrics_store=metrics_store,
    )
    command_store = create_sandbox_manager_command_store()
    command_cursor = "0-0"
    pending_commands: list[dict[str, str]] = []
    try:
        while True:
            await manager.reconcile()
            if command_store is not None:
                try:
                    command_cursor, commands = await command_store.read(after_id=command_cursor)
                except Exception:
                    # Redis is an optional optimization/control input.  Keep
                    # reconciling Docker and retry the stream on the next pass.
                    commands = []
                pending_commands.extend(commands)
                due: list[dict[str, str]] = []
                remaining: list[dict[str, str]] = []
                now = datetime.now(UTC)
                for command in pending_commands:
                    execute_at = command.get("execute_at", "")
                    if execute_at:
                        try:
                            scheduled = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
                        except ValueError:
                            scheduled = now
                        if scheduled.tzinfo is None:
                            scheduled = scheduled.replace(tzinfo=UTC)
                        if scheduled > now:
                            remaining.append(command)
                            continue
                    due.append(command)
                pending_commands = remaining
                for command in due:
                    if command.get("type") != "pool_target" or command.get("profile_id") != "python-base":
                        continue
                    try:
                        await manager.request_target(int(command["target"]))
                    except (KeyError, ValueError):
                        continue
                if due:
                    await manager.refill()
            await asyncio.sleep(max(5, settings.NLP_AGENT_SANDBOX_RECONCILE_INTERVAL_S))
    finally:
        if command_store is not None:
            await command_store.close()
        if adaptive_state_store is not None:
            await adaptive_state_store.close()
        if metrics_store is not None:
            await metrics_store.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
