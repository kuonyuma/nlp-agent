# Sandbox Phase 5 extension boundary

Phase 5 is deliberately opt-in. The Phase 3 gVisor `runsc` backend remains the
default and the only backend enabled by the production examples.

## Runtime adapters

- `KataRuntimeAdapter` uses the same hardened Docker command contract with
  `kata-qemu` and an immutable image digest.
- `FirecrackerRuntimeAdapter` exposes pinned guest inputs and a jailer launch
  command, but guest-agent lifecycle operations fail closed until a Linux
  deployment provides the integration and its security tests.
- `runtime_factory.create_runtime_adapter()` selects a backend explicitly;
  unknown backends are rejected.

## Multi-node scheduling

`SandboxNodeScheduler` filters labels, taints, and available slots before
choosing a deterministic least-loaded node. `KubernetesRuntimeManifest`
produces a reviewable non-root Pod manifest with no service-account token and
all Linux capabilities dropped. Kubernetes API ownership remains with the
isolated Manager when a cluster deployment is introduced.

## Project Storage

Persistent project code is not enabled by default. `DisabledProjectStorage`
is the configured implementation unless the product explicitly sets both
`NLP_AGENT_SANDBOX_PROJECT_STORAGE_ENABLED=true` and a storage root. The local
opt-in implementation validates project-relative paths, rejects symlinks, and
writes files atomically.

## Runtime snapshots

Snapshots remain disabled by default. `RuntimeSnapshotPolicy` requires an
explicit enablement flag, a recognized backend, clean runtime state, and
entropy re-seeding. No snapshot command is issued until the backend-specific
guest lifecycle and restore tests satisfy that gate.
