from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from evaluation.review_blueprint.models import ReviewBlueprintFixture, ReviewDataset


def load_review_dataset(path: str | Path) -> tuple[ReviewDataset, str]:
    source = Path(path)
    content = source.read_bytes()
    raw = yaml.safe_load(content) or {}
    blueprint_source = source.parent / raw.pop("blueprint_path")
    blueprint = ReviewBlueprintFixture.model_validate(yaml.safe_load(blueprint_source.read_text(encoding="utf-8")) or {})
    raw["blueprint_path"] = blueprint_source.name
    raw["blueprint"] = blueprint.model_dump(mode="json")
    dataset = ReviewDataset.model_validate(raw)
    identifiers = [case.id for case in dataset.cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("review dataset contains duplicate case ids")
    for case in dataset.cases:
        if case.learning_context.mode != "review":
            raise ValueError(f"{case.id}: review evaluation requires review mode")
        if case.learning_context.topic_id != blueprint.topic_id:
            raise ValueError(f"{case.id}: learning context must use the fixture topic")
    return dataset, hashlib.sha256(content + blueprint_source.read_bytes()).hexdigest()
