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
from server.sandbox.optimization import PreloadCompatibility, check_preload_compatibility


def preload_probe_source(modules: tuple[str, ...]) -> str:
    encoded = json.dumps(modules)
    return (
        "import importlib.util, json, sys\n"
        f"mods = {encoded}\n"
        "print(json.dumps({'python_version': sys.version.split()[0], 'modules': "
        "{name: importlib.util.find_spec(name) is not None for name in mods}}))\n"
    )


async def benchmark(
    image: str,
    *,
    iterations: int,
    modules: tuple[str, ...] = (),
    profile_id: str = "python-base",
    runtime_version: str = "nova-runtime",
) -> dict[str, object]:
    adapter = DockerRuntimeAdapter(DockerRuntimeConfig(image=image))
    samples: list[dict[str, object]] = []
    image_started = perf_counter()
    image_cached = await adapter.image_cached()
    image_cached_ms = round((perf_counter() - image_started) * 1000, 2)
    for index in range(iterations):
        started = perf_counter()
        result = await adapter.run_scratch(source=preload_probe_source(modules))
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        try:
            probe = json.loads(str(result.get("stdout") or "").strip().splitlines()[-1])
        except (AttributeError, IndexError, json.JSONDecodeError):
            probe = {"python_version": "unknown", "modules": {}}
        samples.append(
            {
                "iteration": index + 1,
                "scratch_ms": elapsed_ms,
                "ok": int(result.get("ok", True)),
                "python_version": str(probe.get("python_version", "unknown")),
                "available_modules": sorted(name for name, present in dict(probe.get("modules", {})).items() if present),
            }
        )
    python_version = str(samples[-1].get("python_version", "unknown")) if samples else "unknown"
    compatibility = check_preload_compatibility(
        PreloadCompatibility(profile_id, image, python_version, runtime_version, modules),
        python_version=python_version,
        runtime_version=runtime_version,
        available_modules=samples[-1].get("available_modules", []) if samples else (),
    )
    return {
        "runtime": adapter.config.runtime,
        "image": image,
        "image_cached": image_cached,
        "image_cached_ms": image_cached_ms,
        "preload_modules": list(modules),
        "compatibility": compatibility.as_dict(),
        "iterations": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="immutable image@sha256 digest")
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 21))
    parser.add_argument("--modules", default="numpy,pandas,matplotlib", help="comma-separated preload modules to probe")
    parser.add_argument("--profile-id", default="python-base")
    parser.add_argument("--runtime-version", default="nova-runtime")
    args = parser.parse_args()
    result = asyncio.run(
        benchmark(
            args.image,
            iterations=args.iterations,
            modules=tuple(item.strip() for item in args.modules.split(",") if item.strip()),
            profile_id=args.profile_id,
            runtime_version=args.runtime_version,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
