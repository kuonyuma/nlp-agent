"""Deterministic multi-node placement primitives for the Phase 5 boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class NodeCapacity:
    node_id: str
    available_slots: int
    labels: Mapping[str, str] = field(default_factory=dict)
    taints: tuple[str, ...] = ()
    zone: str | None = None


class SandboxNodeScheduler:
    """Choose the least-loaded eligible node without talking to Kubernetes."""

    def choose(
        self,
        nodes: list[NodeCapacity],
        *,
        required_labels: Mapping[str, str] | None = None,
        excluded_taints: set[str] | None = None,
    ) -> str:
        required_labels = required_labels or {}
        # A tainted node is excluded by default.  Callers must explicitly
        # name tolerated taints by passing a set of taints to filter instead.
        eligible = [
            node
            for node in nodes
            if node.available_slots > 0
            and all(node.labels.get(key) == value for key, value in required_labels.items())
            and (
                not node.taints
                if excluded_taints is None
                else not excluded_taints.intersection(node.taints)
            )
        ]
        if not eligible:
            raise LookupError("no eligible Sandbox node has available capacity")
        # More free slots means less current load.  Node ID breaks ties so a
        # cluster produces the same placement decision across Manager replicas.
        return min(eligible, key=lambda node: (-node.available_slots, node.node_id)).node_id


class KubernetesRuntimeManifest:
    """Build a reviewable Pod manifest; the Manager still owns lifecycle I/O."""

    @staticmethod
    def build(*, name: str, image: str, node_id: str | None = None) -> dict[str, object]:
        if "@sha256:" not in image:
            raise ValueError("Kubernetes Sandbox image must be pinned by immutable digest")
        spec: dict[str, object] = {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001},
            "containers": [{
                "name": "sandbox",
                "image": image,
                "imagePullPolicy": "IfNotPresent",
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "resources": {"requests": {"cpu": "1", "memory": "768Mi"}, "limits": {"cpu": "1", "memory": "768Mi"}},
            }],
        }
        if node_id:
            spec["nodeName"] = node_id
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"nova.sandbox.managed": "true"}}, "spec": spec}


class KubernetesRuntimeClient(Protocol):
    async def list_nodes(self) -> list[NodeCapacity]: ...
    async def create_pod(self, manifest: dict[str, object]) -> str: ...
    async def delete_pod(self, pod_id: str) -> None: ...
    async def pod_healthy(self, pod_id: str) -> bool: ...
    async def pod_kernel_ready(self, pod_id: str) -> bool: ...
    async def execute(self, pod_id: str, *, source: str) -> dict[str, object]: ...
    async def interrupt(self, pod_id: str) -> None: ...
    async def managed_pod_ids(self) -> set[str]: ...


class KubernetesRuntimeAdapter:
    """Cluster-facing seam; API calls remain owned by the isolated Manager."""

    def __init__(
        self,
        *,
        image: str,
        scheduler: SandboxNodeScheduler | None = None,
        client: KubernetesRuntimeClient | None = None,
    ) -> None:
        if "@sha256:" not in image:
            raise ValueError("Kubernetes Sandbox image must be pinned by immutable digest")
        self.config = type("KubernetesRuntimeConfig", (), {"image": image})()
        self.runtime_kind = "kubernetes"
        self.scheduler = scheduler or SandboxNodeScheduler()
        self.client = client

    @property
    def image_digest(self) -> str:
        return self.config.image

    def create_manifest(
        self,
        *,
        name: str,
        nodes: list[NodeCapacity],
        required_labels: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        node_id = self.scheduler.choose(nodes, required_labels=required_labels)
        return KubernetesRuntimeManifest.build(name=name, image=self.config.image, node_id=node_id)

    def _client(self) -> KubernetesRuntimeClient:
        if self.client is None:
            raise RuntimeError("Kubernetes Sandbox Manager client is not configured")
        return self.client

    async def image_cached(self) -> bool:
        # Image pull/caching is owned by Kubernetes; create_ready submits a Pod.
        return False

    async def create_l1(self, *, name: str) -> str:
        return await self.create_ready(name=name, claim_nonce="")

    async def start_l1(self, external_runtime_id: str) -> None:
        del external_runtime_id

    async def create_ready(self, *, name: str, claim_nonce: str) -> str:
        del claim_nonce
        client = self._client()
        nodes = await client.list_nodes()
        manifest = self.create_manifest(name=name, nodes=nodes, required_labels={"sandbox": "true"})
        return await client.create_pod(manifest)

    async def destroy(self, external_runtime_id: str) -> None:
        await self._client().delete_pod(external_runtime_id)

    async def healthy(self, external_runtime_id: str) -> bool:
        return await self._client().pod_healthy(external_runtime_id)

    async def kernel_ready(self, external_runtime_id: str) -> bool:
        return await self._client().pod_kernel_ready(external_runtime_id)

    async def execute(
        self,
        external_runtime_id: str,
        *,
        source: str,
        timeout_seconds: int = 15,
        output_limit_bytes: int = 1_000_000,
    ) -> dict[str, object]:
        del timeout_seconds, output_limit_bytes
        return await self._client().execute(external_runtime_id, source=source)

    async def interrupt(self, external_runtime_id: str) -> None:
        await self._client().interrupt(external_runtime_id)

    async def managed_runtime_ids(self) -> set[str]:
        return await self._client().managed_pod_ids()

    async def run_scratch(self, *, source: str, timeout_seconds: int = 15, output_limit_bytes: int = 1_000_000) -> dict[str, object]:
        del timeout_seconds, output_limit_bytes
        runtime_id = await self.create_ready(name="nova-scratch", claim_nonce="")
        try:
            return await self.execute(runtime_id, source=source)
        finally:
            await self.destroy(runtime_id)
