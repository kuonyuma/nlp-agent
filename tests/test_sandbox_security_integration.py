"""Opt-in Linux/gVisor integration checks; skipped on developer machines."""
from __future__ import annotations

import os
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_SANDBOX_DOCKER_INTEGRATION") != "1", reason="Linux gVisor CI only")


def test_runsc_container_denies_network_and_docker_socket() -> None:
    image = os.environ["NLP_AGENT_SANDBOX_INTEGRATION_IMAGE"]
    name = f"nova-security-{uuid.uuid4().hex}"
    command = ["docker", "run", "--detach", "--name", name, "--runtime", "runsc", "--read-only", "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true", "--memory", "768m", "--cpus", "1", "--pids-limit", "128", "--tmpfs", "/workspace:rw,nosuid,nodev,size=256m", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--tmpfs", "/run/nova:rw,nosuid,nodev,uid=10001,gid=10001,mode=700,size=16m", "--user", "10001:10001", image]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        network = subprocess.run(["docker", "exec", name, "python", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), timeout=1)"], capture_output=True, text=True)
        socket_check = subprocess.run(["docker", "exec", name, "python", "-c", "import os; raise SystemExit(os.path.exists('/var/run/docker.sock'))"], capture_output=True, text=True)
        assert network.returncode != 0
        assert socket_check.returncode == 0
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, text=True)
