from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from evaluation.exercise_blueprint.models import ExerciseBlueprintFixture, ExerciseDataset


def load_exercise_dataset(path: str | Path) -> tuple[ExerciseDataset, str]:
    source = Path(path)
    content = source.read_bytes()
    raw = yaml.safe_load(content) or {}
    blueprint_source = source.parent / raw.pop("blueprint_path")
    blueprint = ExerciseBlueprintFixture.model_validate(yaml.safe_load(blueprint_source.read_text(encoding="utf-8")) or {})
    raw["blueprint_path"] = blueprint_source.name
    raw["blueprint"] = blueprint.model_dump(mode="json")
    dataset = ExerciseDataset.model_validate(raw)
    case_ids = [case.id for case in dataset.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("exercise dataset contains duplicate case ids")
    for case in dataset.cases:
        if case.learning_context.mode != "practice":
            raise ValueError(f"{case.id}: exercise evaluation requires practice mode")
        if case.learning_context.topic_id != blueprint.topic_id:
            raise ValueError(f"{case.id}: learning context must use the fixture topic")
    return dataset, hashlib.sha256(content + blueprint_source.read_bytes()).hexdigest()
