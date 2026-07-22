"""Metrics for ranked retrieval results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def precision_at_n(*, ranked_results: Sequence[dict[str, Any]], ks: Sequence[int]) -> dict[str, Any]:
    if not ks or any(k < 1 for k in ks):
        raise ValueError("ks must contain positive integers")
    ranking = [
        {"rank": index, "id": item["id"], "relevant": bool(item["relevant"])}
        for index, item in enumerate(ranked_results, start=1)
    ]
    metrics = []
    for k in sorted(set(ks)):
        relevant_count = sum(1 for item in ranking[:k] if item["relevant"])
        metrics.append({
            "k": k,
            "relevant_count": relevant_count,
            "precision_at_k": relevant_count / k,
        })
    return {"metrics": metrics, "ranking": ranking}
