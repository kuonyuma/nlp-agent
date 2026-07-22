from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from evaluation.guided.models import GuidedBlueprintFixture, GuidedDataset


def load_guided_dataset(path: str | Path) -> tuple[GuidedDataset, str]:
    """Load a suite and its local fixture without registering it in production."""

    source = Path(path)
    content = source.read_bytes()
    raw = yaml.safe_load(content) or {}
    blueprint_source = source.parent / raw.pop("blueprint_path")
    blueprint = GuidedBlueprintFixture.model_validate(
        yaml.safe_load(blueprint_source.read_text(encoding="utf-8")) or {}
    )
    raw["blueprint_path"] = blueprint_source.name
    raw["blueprint"] = blueprint.model_dump(mode="json")
    dataset = GuidedDataset.model_validate(raw)
    identifiers = [case.id for case in dataset.cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("guided dataset contains duplicate case ids")
    for case in dataset.cases:
        if case.learning_context.mode != "socratic":
            raise ValueError(f"{case.id}: guided evaluation requires socratic mode")
        if case.learning_context.topic_id != blueprint.topic_id:
            raise ValueError(f"{case.id}: learning context must use the fixture topic")
    digest = hashlib.sha256(content + blueprint_source.read_bytes()).hexdigest()
    return dataset, digest
