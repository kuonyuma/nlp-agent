"""BLEU calculation matching the course's precision, geometric mean and BP."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from core.nlp.ngrams import clipped_matches
from core.nlp.tokenization import Tokenization, tokenize


def score_bleu(
    *, candidate: str | Sequence[str], references: Sequence[str | Sequence[str]], max_n: int,
    tokenization: Tokenization,
) -> dict[str, Any]:
    if not references:
        raise ValueError("at least one reference is required")
    if not 1 <= max_n <= 4:
        raise ValueError("max_n must be between 1 and 4")
    candidate_tokens = tokenize(candidate, tokenization)
    reference_tokens = [tokenize(reference, tokenization) for reference in references]
    candidate_length = len(candidate_tokens)
    reference_length = min(
        (len(tokens) for tokens in reference_tokens),
        key=lambda length: (abs(length - candidate_length), length),
    )
    precisions = []
    for n in range(1, max_n + 1):
        matched, total, _, _ = clipped_matches(candidate_tokens, reference_tokens, n)
        precisions.append({"n": n, "matched": matched, "total": total,
                           "precision": matched / total if total else 0.0})
    geometric_mean = (
        math.exp(sum(math.log(item["precision"]) for item in precisions) / max_n)
        if all(item["precision"] > 0 for item in precisions) else 0.0
    )
    brevity_penalty = 1.0 if candidate_length > reference_length else (
        math.exp(1 - reference_length / candidate_length) if candidate_length else 0.0
    )
    return {
        "candidate_length": candidate_length,
        "reference_length": reference_length,
        "modified_precisions": precisions,
        "geometric_mean": geometric_mean,
        "brevity_penalty": brevity_penalty,
        "bleu": brevity_penalty * geometric_mean,
    }


def score_corpus_bleu(
    *, candidates: Sequence[str | Sequence[str]],
    references_per_candidate: Sequence[Sequence[str | Sequence[str]]],
    max_n: int,
    tokenization: Tokenization,
) -> dict[str, Any]:
    if not candidates or len(candidates) != len(references_per_candidate):
        raise ValueError("candidates and references_per_candidate must be non-empty and aligned")
    if not 1 <= max_n <= 4:
        raise ValueError("max_n must be between 1 and 4")
    matched_by_n = [0] * max_n
    total_by_n = [0] * max_n
    candidate_length = 0
    reference_length = 0
    for candidate, references in zip(candidates, references_per_candidate):
        if not references:
            raise ValueError("every candidate requires at least one reference")
        candidate_tokens = tokenize(candidate, tokenization)
        reference_tokens = [tokenize(reference, tokenization) for reference in references]
        candidate_length += len(candidate_tokens)
        reference_length += min(
            (len(tokens) for tokens in reference_tokens),
            key=lambda length: (abs(length - len(candidate_tokens)), length),
        )
        for n in range(1, max_n + 1):
            matched, total, _, _ = clipped_matches(candidate_tokens, reference_tokens, n)
            matched_by_n[n - 1] += matched
            total_by_n[n - 1] += total
    precisions = [
        {"n": n, "matched": matched_by_n[n - 1], "total": total_by_n[n - 1],
         "precision": matched_by_n[n - 1] / total_by_n[n - 1] if total_by_n[n - 1] else 0.0}
        for n in range(1, max_n + 1)
    ]
    geometric_mean = (
        math.exp(sum(math.log(item["precision"]) for item in precisions) / max_n)
        if all(item["precision"] > 0 for item in precisions) else 0.0
    )
    brevity_penalty = 1.0 if candidate_length > reference_length else (
        math.exp(1 - reference_length / candidate_length) if candidate_length else 0.0
    )
    return {
        "mode": "corpus",
        "candidate_length": candidate_length,
        "reference_length": reference_length,
        "modified_precisions": precisions,
        "geometric_mean": geometric_mean,
        "brevity_penalty": brevity_penalty,
        "bleu": brevity_penalty * geometric_mean,
    }
