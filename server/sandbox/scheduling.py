"""Deterministic multi-node placement primitives for the Phase 5 boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


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
        excluded_taints = excluded_taints or set()
        eligible = [
            node
            for node in nodes
            if node.available_slots > 0
            and all(node.labels.get(key) == value for key, value in required_labels.items())
            and not excluded_taints.intersection(node.taints)
        ]
        if not eligible:
            raise LookupError("no eligible Sandbox node has available capacity")
        return min(eligible, key=lambda node: (node.available_slots, node.node_id)).node_id


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


class KubernetesRuntimeAdapter:
    """Cluster-facing seam; API calls remain owned by the isolated Manager."""

    def __init__(self, *, image: str, scheduler: SandboxNodeScheduler | None = None) -> None:
        if "@sha256:" not in image:
            raise ValueError("Kubernetes Sandbox image must be pinned by immutable digest")
        self.image = image
        self.scheduler = scheduler or SandboxNodeScheduler()

    def create_manifest(
        self,
        *,
        name: str,
        nodes: list[NodeCapacity],
        required_labels: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        node_id = self.scheduler.choose(nodes, required_labels=required_labels)
        return KubernetesRuntimeManifest.build(name=name, image=self.image, node_id=node_id)
