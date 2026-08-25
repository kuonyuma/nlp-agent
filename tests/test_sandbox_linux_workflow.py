from __future__ import annotations

from pathlib import Path


def test_linux_smoke_uses_the_registered_gvisor_runtime() -> None:
    workflow = Path(".github/workflows/sandbox-linux.yml").read_text(encoding="utf-8")
    auth_lifecycle = workflow.split("  sandbox-auth-lifecycle:", 1)[1].split(
        "  sandbox-manager-runsc:", 1
    )[0]

    assert "docker info --format '{{json .Runtimes}}'" in workflow
    assert "--runtime runsc" in workflow
    assert "RUN_SANDBOX_DOCKER_INTEGRATION=1" in workflow
    assert "RUN_SANDBOX_REDIS_INTEGRATION=1" in workflow
    assert "NLP_AGENT_DOCKER_RUNTIME: runsc" in workflow
    assert "Install gVisor runsc for lifecycle tests" not in auth_lifecycle
    assert "NLP_AGENT_DOCKER_RUNTIME: runsc" not in auth_lifecycle
    assert "sandbox-manager-runsc" in workflow
    assert "docker run --detach --name nova-ci-mysql" in workflow
    assert "--measure-manager-claim" in workflow
    assert "sandbox-manager-claim-benchmark" in workflow
    assert "feature/sandbox-phase3-develop" in workflow
    assert "pip install -e ." not in workflow
    assert "pip install -r requirements.txt" in workflow
