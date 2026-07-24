"""Suite discovery and path conventions for evaluation assets.

Callers use a suite id; this module keeps dataset, run, and Markdown-result
locations consistent without requiring each new suite to change Python code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITES_ROOT = ROOT / ".jbeval" / "suites"
DEFAULT_RUNS_ROOT = ROOT / ".jbeval" / "runs"
DEFAULT_RESULTS_ROOT = ROOT / "evaluation" / "result"


@dataclass(frozen=True)
class EvaluationSuite:
    """All stable paths belonging to one evaluation suite."""

    id: str
    name: str
    dataset_path: Path
    runs_dir: Path
    results_dir: Path


def _load_suite_metadata(dataset_path: Path) -> tuple[str, str]:
    """Read catalog metadata without imposing a runner-specific case schema."""
    raw = yaml.safe_load(dataset_path.read_bytes()) or {}
    suite = raw.get("suite")
    if not isinstance(suite, dict):
        raise ValueError(f"Evaluation dataset has no suite metadata: {dataset_path}")
    suite_id = suite.get("id")
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise ValueError(f"Evaluation dataset has no suite id: {dataset_path}")
    name = suite.get("name", suite_id)
    return suite_id, name if isinstance(name, str) else suite_id


def discover_suites(
    *,
    suites_root: Path = DEFAULT_SUITES_ROOT,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    results_root: Path = DEFAULT_RESULTS_ROOT,
) -> dict[str, EvaluationSuite]:
    """Discover every ``<suite-id>/dataset.yaml`` and derive its storage paths."""
    discovered: dict[str, EvaluationSuite] = {}
    if not suites_root.exists():
        return discovered
    for dataset_path in sorted(suites_root.glob("*/dataset.yaml")):
        suite_id, suite_name = _load_suite_metadata(dataset_path)
        if suite_id in discovered:
            raise ValueError(f"Duplicate evaluation suite id: {suite_id}")
        discovered[suite_id] = EvaluationSuite(
            id=suite_id,
            name=suite_name,
            dataset_path=dataset_path,
            runs_dir=runs_root / suite_id,
            results_dir=results_root / suite_id,
        )
    return discovered


def resolve_suite(reference: str, *, suites: dict[str, EvaluationSuite] | None = None) -> EvaluationSuite:
    """Return one discovered suite by id with an actionable error for callers."""
    available = suites if suites is not None else discover_suites()
    try:
        return available[reference]
    except KeyError as error:
        choices = ", ".join(available) or "(none)"
        raise ValueError(f"Unknown evaluation suite {reference!r}. Available: {choices}") from error


def resolve_suite_reference(reference: str, *, suites: dict[str, EvaluationSuite] | None = None) -> EvaluationSuite:
    """Resolve a suite id, while retaining compatibility with a dataset file path."""
    candidate = Path(reference)
    if candidate.is_file():
        suite_id, suite_name = _load_suite_metadata(candidate)
        return EvaluationSuite(
            id=suite_id,
            name=suite_name,
            dataset_path=candidate,
            runs_dir=DEFAULT_RUNS_ROOT / suite_id,
            results_dir=DEFAULT_RESULTS_ROOT / suite_id,
        )
    return resolve_suite(reference, suites=suites)


def latest_run_path(runs_dir: Path) -> Path | None:
    """Return the newest timestamp-named report under one suite's run directory."""
    reports = [path for path in runs_dir.rglob("*.json") if path.is_file()]
    # Run files are named ``YYYYMMDD-HHMMSS.json``.  Prefer that stable
    # timestamp and use mtime only as a tie-breaker; Windows can give rapidly
    # written files the same mtime, which otherwise makes catalog selection
    # non-deterministic.
    return max(reports, key=lambda path: (path.stem, path.stat().st_mtime_ns)) if reports else None
