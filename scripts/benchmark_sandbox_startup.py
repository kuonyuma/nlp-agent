"""Measure Sandbox startup stages on the target Linux/runsc host.

This intentionally is an opt-in operator script: it never claims a local
Windows result.  Run it in the CI/Linux job with a pinned image and persist the
JSON output as a workflow artifact for the preload compatibility matrix.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
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


def percentile(values: list[float], quantile: float) -> float | None:
    """Return a deterministic linear-interpolated percentile for CI reports."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


async def benchmark(
    image: str,
    *,
    iterations: int,
    modules: tuple[str, ...] = (),
    profile_id: str = "python-base",
    runtime_version: str = "nova-runtime",
    matrix_path: Path | None = None,
    update_matrix: bool = False,
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
        stages: dict[str, float | str] = {}
        warm_runtime_id: str | None = None
        try:
            stage_started = perf_counter()
            warm_runtime_id = await adapter.create_l1(name=f"nova-benchmark-{index + 1}")
            stages["create_ms"] = round((perf_counter() - stage_started) * 1000, 2)
            stage_started = perf_counter()
            await adapter.start_l1(warm_runtime_id)
            stages["start_ms"] = round((perf_counter() - stage_started) * 1000, 2)
            stage_started = perf_counter()
            ready = False
            for _ in range(60):
                if await adapter.kernel_ready(warm_runtime_id):
                    ready = True
                    break
                await asyncio.sleep(0.5)
            stages["kernel_ready_ms"] = round((perf_counter() - stage_started) * 1000, 2)
            if not ready:
                raise TimeoutError("benchmark kernel did not become ready")
            stage_started = perf_counter()
            # In production this interval is the DB claim + ticket handoff;
            # the benchmark records the isolated runtime handoff separately.
            claimed_runtime_id = warm_runtime_id
            stages["claim_ms"] = round((perf_counter() - stage_started) * 1000, 2)
            stage_started = perf_counter()
            first_output = await adapter.execute(
                claimed_runtime_id,
                source=preload_probe_source(modules),
                timeout_seconds=15,
                output_limit_bytes=1_000_000,
            )
            stages["first_output_ms"] = round((perf_counter() - stage_started) * 1000, 2)
            try:
                probe = json.loads(str(first_output.get("stdout") or "").strip().splitlines()[-1])
            except (AttributeError, IndexError, json.JSONDecodeError):
                pass
        except Exception as error:
            stages["error"] = f"{type(error).__name__}: {error}"[:200]
        finally:
            if warm_runtime_id:
                try:
                    await adapter.destroy(warm_runtime_id)
                except Exception:
                    pass
        samples.append(
            {
                "iteration": index + 1,
                "scratch_ms": elapsed_ms,
                "ok": int(result.get("ok", True)),
                "python_version": str(probe.get("python_version", "unknown")),
                "available_modules": sorted(name for name, present in dict(probe.get("modules", {})).items() if present),
                "stages": stages,
            }
        )
    python_version = str(samples[-1].get("python_version", "unknown")) if samples else "unknown"
    compatibility = check_preload_compatibility(
        PreloadCompatibility(profile_id, image, python_version, runtime_version, modules),
        python_version=python_version,
        runtime_version=runtime_version,
        available_modules=samples[-1].get("available_modules", []) if samples else (),
    )
    output = {
        "runtime": adapter.config.runtime,
        "image": image,
        "image_cached": image_cached,
        "image_cached_ms": image_cached_ms,
        "preload_modules": list(modules),
        "compatibility": compatibility.as_dict(),
        "iterations": samples,
        "stage_percentiles_ms": {
            stage: {
                quantile: percentile(
                    [
                        float(row["stages"][stage])
                        for row in samples
                        if isinstance(row.get("stages"), dict)
                        and isinstance(row["stages"].get(stage), (int, float))
                    ],
                    probability,
                )
                for quantile, probability in (("p50", 0.50), ("p95", 0.95))
            }
            for stage in ("create_ms", "start_ms", "kernel_ready_ms", "claim_ms", "first_output_ms")
        },
    }
    if update_matrix and matrix_path is not None:
        update_preload_matrix(matrix_path, compatibility, output)
        output["matrix_updated"] = str(matrix_path)
    return output


def update_preload_matrix(
    path: Path, compatibility: PreloadCompatibility, benchmark_result: dict[str, object]
) -> None:
    """Persist the CI result into the operator-visible compatibility matrix."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = {"version": 1, "profiles": {}}
    if not isinstance(payload, dict):
        payload = {"version": 1, "profiles": {}}
    profiles = payload.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        payload["profiles"] = profiles
    row = dict(compatibility.as_dict())
    row["image_digest"] = compatibility.image_digest
    row["measured_at"] = datetime.now(UTC).isoformat()
    row["benchmark"] = {
        "iterations": len(benchmark_result.get("iterations", [])),
        "image_cached": benchmark_result.get("image_cached"),
        "stage_percentiles_ms": benchmark_result.get("stage_percentiles_ms", {}),
    }
    profiles[compatibility.profile_id] = row
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="immutable image@sha256 digest")
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 21))
    parser.add_argument("--modules", default="numpy,pandas,matplotlib", help="comma-separated preload modules to probe")
    parser.add_argument("--profile-id", default="python-base")
    parser.add_argument("--runtime-version", default="nova-runtime")
    parser.add_argument("--matrix-path", type=Path)
    parser.add_argument("--update-matrix", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        benchmark(
            args.image,
            iterations=args.iterations,
            modules=tuple(item.strip() for item in args.modules.split(",") if item.strip()),
            profile_id=args.profile_id,
            runtime_version=args.runtime_version,
            matrix_path=args.matrix_path,
            update_matrix=args.update_matrix,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
