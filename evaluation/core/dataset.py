from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from evaluation.core.models import Dataset


def load_dataset(path: str | Path) -> tuple[Dataset, str]:
    source = Path(path)
    content = source.read_bytes()
    raw = yaml.safe_load(content) or {}
    defaults = raw.get("defaults", {}).get("expectation", {})
    for case in raw.get("cases", []):
        case["expectation"] = {**defaults, **case.get("expectation", {})}
    dataset = Dataset.model_validate(raw)
    identifiers = [case.id for case in dataset.cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("dataset contains duplicate case ids")
    for case in dataset.cases:
        expectation = case.expectation
        if expectation.expected_no_tool and expectation.required_tools:
            raise ValueError(f"{case.id}: expected_no_tool cannot require tools")
        if set(expectation.required_tools) & set(expectation.forbidden_tools):
            raise ValueError(f"{case.id}: a tool cannot be required and forbidden")
        if not set(expectation.ordered_tools) <= set(expectation.required_tools):
            raise ValueError(f"{case.id}: ordered_tools must be required")
        if expectation.worker_required_tools and expectation.min_workers == 0:
            raise ValueError(f"{case.id}: worker_required_tools needs min_workers")
        if expectation.min_dispatches and expectation.min_workers == 0:
            raise ValueError(f"{case.id}: min_dispatches needs min_workers")
        if expectation.max_workers is not None and expectation.max_workers < expectation.min_workers:
            raise ValueError(f"{case.id}: max_workers cannot be below min_workers")
        if expectation.max_dispatches is not None and expectation.max_dispatches < expectation.min_dispatches:
            raise ValueError(f"{case.id}: max_dispatches cannot be below min_dispatches")
    return dataset, hashlib.sha256(content).hexdigest()


def dataset_summary(dataset: Dataset) -> dict[str, Any]:
    return {
        "suite_id": dataset.suite.get("id", "unknown"),
        "cases": len(dataset.cases),
        "tools": sorted({tool for case in dataset.cases for tool in case.expectation.required_tools}),
    }
