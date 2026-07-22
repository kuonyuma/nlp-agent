"""Threshold-based precision, recall, and F1 calculations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def precision_recall_curve(*, labels: Sequence[int], scores: Sequence[float]) -> dict[str, Any]:
    if not labels or len(labels) != len(scores):
        raise ValueError("labels and scores must be non-empty and have equal lengths")
    if any(label not in {0, 1} for label in labels):
        raise ValueError("labels must be binary values")
    thresholds = sorted(set(scores), reverse=True)
    points = []
    for threshold in thresholds:
        predictions = [score >= threshold for score in scores]
        tp = sum(label == 1 and predicted for label, predicted in zip(labels, predictions))
        fp = sum(label == 0 and predicted for label, predicted in zip(labels, predictions))
        fn = sum(label == 1 and not predicted for label, predicted in zip(labels, predictions))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        points.append({
            "threshold": threshold, "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
        })
    best = max(points, key=lambda point: (point["f1"], point["threshold"]))
    return {"points": points, "best_f1": best}
