from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_kata_adapter_preserves_hardened_runtime_contract() -> None:
    from server.sandbox.runtime_adapters import KataRuntimeAdapter, KataRuntimeConfig

    adapter = KataRuntimeAdapter(KataRuntimeConfig(image="nova@sha256:" + "a" * 64))
    command = adapter.create_command(name="runtime-1", claim_nonce="secret")

    assert command[0:4] == ("docker", "run", "--detach", "--name")
    assert ("--runtime", "kata-qemu") == command[command.index("--runtime") : command.index("--runtime") + 2]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "secret" not in command


def test_firecracker_adapter_requires_explicit_pinned_guest_inputs() -> None:
    from server.sandbox.runtime_adapters import FirecrackerRuntimeAdapter, FirecrackerRuntimeConfig

    with pytest.raises(ValueError):
        FirecrackerRuntimeConfig(kernel_image="kernel", rootfs_image="rootfs")
    adapter = FirecrackerRuntimeAdapter(
        FirecrackerRuntimeConfig(
            kernel_image="kernel@sha256:" + "b" * 64,
            rootfs_image="rootfs@sha256:" + "c" * 64,
        )
    )
    command = adapter.launch_command(runtime_id="runtime-1")
    assert command[:3] == ("jailer", "--id", "runtime-1")
    assert "--exec-file" in command
    assert "kernel@sha256:" + "b" * 64 not in command


def test_multi_node_scheduler_filters_capacity_and_taints_deterministically() -> None:
    from server.sandbox.scheduling import KubernetesRuntimeAdapter, KubernetesRuntimeManifest, NodeCapacity, SandboxNodeScheduler

    scheduler = SandboxNodeScheduler()
    nodes = [
        NodeCapacity("node-a", available_slots=2, labels={"sandbox": "true"}),
        NodeCapacity("node-d", available_slots=4, labels={"sandbox": "true"}),
        NodeCapacity("node-b", available_slots=5, labels={"sandbox": "true"}, taints=("drain",)),
        NodeCapacity("node-c", available_slots=4, labels={"sandbox": "false"}),
    ]
    assert scheduler.choose(nodes, required_labels={"sandbox": "true"}) == "node-d"
    with pytest.raises(LookupError):
        scheduler.choose([NodeCapacity("node-a", available_slots=0, labels={"sandbox": "true"})], required_labels={"sandbox": "true"})
    manifest = KubernetesRuntimeManifest.build(name="runtime-1", image="nova@sha256:" + "e" * 64, node_id="node-a")
    assert manifest["spec"]["nodeName"] == "node-a"
    assert manifest["spec"]["automountServiceAccountToken"] is False
    assert manifest["spec"]["containers"][0]["securityContext"]["capabilities"]["drop"] == ["ALL"]
    adapter = KubernetesRuntimeAdapter(image="nova@sha256:" + "f" * 64)
    assert adapter.create_manifest(name="runtime-2", nodes=nodes, required_labels={"sandbox": "true"})["spec"]["nodeName"] == "node-d"


def test_project_storage_is_disabled_without_explicit_product_opt_in(tmp_path) -> None:
    from server.sandbox.project_storage import DisabledProjectStorage, LocalProjectStorage

    disabled = DisabledProjectStorage()
    with pytest.raises(PermissionError):
        disabled.put("project-1", "main.py", b"print(1)")
    storage = LocalProjectStorage(tmp_path, enabled=True)
    storage.put("project-1", "main.py", b"print(1)")
    assert storage.get("project-1", "main.py") == b"print(1)"
    with pytest.raises(ValueError):
        storage.put("project-1", "../escape.py", b"no")
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"outside")
    link = tmp_path / "project-1" / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not permitted by this Windows runner")
    with pytest.raises(ValueError):
        storage.get("project-1", "link.py")


def test_runtime_snapshot_requires_safety_gate_and_explicit_capability() -> None:
    from server.sandbox.snapshots import RuntimeSnapshotPolicy, SnapshotCapability

    policy = RuntimeSnapshotPolicy(enabled=False)
    with pytest.raises(PermissionError):
        policy.authorize(SnapshotCapability(backend="runsc", clean=True, entropy_reseeded=True))
    policy = RuntimeSnapshotPolicy(enabled=True)
    with pytest.raises(PermissionError):
        policy.authorize(SnapshotCapability(backend="runsc", clean=False, entropy_reseeded=True))
    assert policy.authorize(SnapshotCapability(backend="runsc", clean=True, entropy_reseeded=True)) is True


def test_runtime_factory_keeps_runsc_default_and_supports_kata_opt_in() -> None:
    from server.sandbox.docker_runtime import DockerRuntimeAdapter
    from server.sandbox.runtime_adapters import (
        FirecrackerRuntimeAdapter,
        KataRuntimeAdapter,
        SandboxRuntimeAdapter,
    )
    from server.sandbox.runtime_factory import create_runtime_adapter
    from server.sandbox.scheduling import KubernetesRuntimeAdapter

    image = "nova@sha256:" + "d" * 64
    runsc = create_runtime_adapter(backend="runsc", image=image)
    kata = create_runtime_adapter(backend="kata", image=image)
    kubernetes = create_runtime_adapter(backend="kubernetes", image=image, client=object())
    firecracker = create_runtime_adapter(
        backend="firecracker",
        image=image,
        kernel_image="kernel@sha256:" + "2" * 64,
        rootfs_image="rootfs@sha256:" + "3" * 64,
    )
    assert isinstance(runsc, DockerRuntimeAdapter)
    assert isinstance(kata, KataRuntimeAdapter)
    assert isinstance(kubernetes, KubernetesRuntimeAdapter)
    assert isinstance(firecracker, FirecrackerRuntimeAdapter)
    assert all(
        isinstance(adapter, SandboxRuntimeAdapter)
        for adapter in (runsc, kata, kubernetes, firecracker)
    )
    with pytest.raises(ValueError):
        create_runtime_adapter(backend="unknown", image=image)


def test_project_storage_factory_is_disabled_by_default() -> None:
    from server.sandbox.project_storage import DisabledProjectStorage, create_project_storage

    assert isinstance(create_project_storage(enabled=False, root=None), DisabledProjectStorage)


@pytest.mark.asyncio
async def test_kubernetes_adapter_delegates_lifecycle_to_manager_owned_client() -> None:
    from server.sandbox.scheduling import KubernetesRuntimeAdapter, NodeCapacity

    class FakeKubernetesClient:
        async def list_nodes(self):
            return [NodeCapacity("node-a", 2, {"sandbox": "true"})]

        async def create_pod(self, manifest):
            assert manifest["spec"]["nodeName"] == "node-a"
            return "pod-1"

        async def delete_pod(self, pod_id):
            assert pod_id == "pod-1"

        async def pod_healthy(self, pod_id):
            return pod_id == "pod-1"

        async def pod_kernel_ready(self, pod_id):
            return pod_id == "pod-1"

        async def execute(self, pod_id, *, source):
            return {"status": "completed", "stdout": source}

        async def interrupt(self, pod_id):
            return None

        async def managed_pod_ids(self):
            return {"pod-1"}

    adapter = KubernetesRuntimeAdapter(image="nova@sha256:" + "1" * 64, client=FakeKubernetesClient())
    pod_id = await adapter.create_ready(name="runtime-1", claim_nonce="ignored")
    assert pod_id == "pod-1"
    assert await adapter.kernel_ready(pod_id)
    assert await adapter.execute(pod_id, source="print(1)") == {"status": "completed", "stdout": "print(1)"}
    await adapter.destroy(pod_id)
