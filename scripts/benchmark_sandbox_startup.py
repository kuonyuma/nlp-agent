"""Measure Sandbox startup stages on the target Linux/runsc host.

This intentionally is an opt-in operator script: it never claims a local
Windows result.  Run it in the CI/Linux job with a pinned image and persist the
JSON output as a workflow artifact for the preload compatibility matrix.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.sandbox.docker_runtime import DockerRuntimeAdapter, DockerRuntimeConfig


async def benchmark(image: str, *, iterations: int) -> dict[str, object]:
    adapter = DockerRuntimeAdapter(DockerRuntimeConfig(image=image))
    samples: list[dict[str, float | int]] = []
    for index in range(iterations):
        started = perf_counter()
        result = await adapter.run_scratch(source="import sys; print(sys.version)")
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        samples.append({"iteration": index + 1, "scratch_ms": elapsed_ms, "ok": int(result.get("ok", True))})
    return {"runtime": adapter.config.runtime, "image": image, "iterations": samples}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="immutable image@sha256 digest")
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 21))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(args.image, iterations=args.iterations)), indent=2))


if __name__ == "__main__":
    main()
