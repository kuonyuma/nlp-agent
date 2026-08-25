from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_adaptive_pool_target_is_bounded_and_uses_refill_p95() -> None:
    from server.sandbox.optimization import AdaptivePoolPolicy

    policy = AdaptivePoolPolicy(ready_min=1, ready_max=5, burst_buffer=1)
    assert policy.target_for(arrival_rate_per_min=30, refill_p95_s=4) == 3
    assert policy.target_for(arrival_rate_per_min=10_000, refill_p95_s=60) == 5


def test_class_forecast_and_cooldown_are_deterministic() -> None:
    from server.sandbox.optimization import AdaptivePoolPolicy

    policy = AdaptivePoolPolicy(ready_min=1, ready_max=10, burst_buffer=2, cooldown=timedelta(seconds=30))
    assert policy.target_before_class(expected_sessions=8, sessions_per_runtime=2) == 6
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert not policy.should_scale(current_target=1, desired_target=3, last_scaled_at=stamp, now=stamp + timedelta(seconds=1))
    assert policy.should_scale(current_target=1, desired_target=3, last_scaled_at=stamp, now=stamp + timedelta(seconds=30))


def test_preload_matrix_marks_missing_dependency_incompatible() -> None:
    from server.sandbox.optimization import PreloadCompatibility, check_preload_compatibility

    row = check_preload_compatibility(
        PreloadCompatibility("python-base", "python@sha256:x", "3.12", "nova-1", ("numpy", "pandas")),
        python_version="3.12", runtime_version="nova-1", available_modules=("numpy",),
    )
    assert row.status == "incompatible"
    assert "pandas" in row.notes


def test_fault_injection_is_opt_in_and_named() -> None:
    from server.sandbox.faults import SandboxFaultInjector, SandboxInjectedFault

    SandboxFaultInjector.from_env("").fail_if_configured("docker.create")
    with pytest.raises(SandboxInjectedFault):
        SandboxFaultInjector.from_env("docker.create").fail_if_configured("docker.create")


def test_preload_matrix_is_operator_visible() -> None:
    from pathlib import Path

    from server.sandbox.optimization import load_preload_matrix

    matrix = load_preload_matrix(Path("configs/sandbox_preload_matrix.json"))
    assert matrix["available"] is True
    assert "python-base" in matrix["profiles"]


@pytest.mark.asyncio
async def test_adaptive_state_store_persists_target_and_cooldown() -> None:
    from server.sandbox.metrics import RedisSandboxAdaptiveStateStore

    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, object] = {}

        async def hgetall(self, _key: str) -> dict[str, object]:
            return self.values

        async def hset(self, _key: str, *, mapping: dict[str, object]) -> None:
            self.values.update(mapping)

    store = RedisSandboxAdaptiveStateStore(FakeRedis())
    assert await store.load() == (None, None)
    await store.save(target=4, scaled_at=12.5)
    assert await store.load() == (4, 12.5)
