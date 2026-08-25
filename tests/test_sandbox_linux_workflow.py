from __future__ import annotations

from pathlib import Path


def test_linux_smoke_uses_the_registered_gvisor_runtime() -> None:
    workflow = Path(".github/workflows/sandbox-linux.yml").read_text(encoding="utf-8")

    assert "docker info --format '{{json .Runtimes}}'" in workflow
    assert "--runtime runsc" in workflow
    assert "RUN_SANDBOX_DOCKER_INTEGRATION=1" in workflow
    assert "RUN_SANDBOX_REDIS_INTEGRATION=1" in workflow
    assert "NLP_AGENT_DOCKER_RUNTIME: runsc" in workflow
    assert "Install gVisor runsc for lifecycle tests" in workflow
    assert "feature/sandbox-phase3-develop" in workflow
    assert "pip install -e ." not in workflow
    assert "pip install -r requirements.txt" in workflow
