"""N-gram generation and BLEU-style clipped matching."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from core.nlp.tokenization import Tokenization, tokenize


def ngram_counts(tokens: Sequence[str], n: int) -> Counter[tuple[str, ...]]:
    if n < 1:
        raise ValueError("n must be at least 1")
    return Counter(tuple(tokens[index:index + n]) for index in range(max(0, len(tokens) - n + 1)))


def clipped_matches(
    candidate_tokens: Sequence[str], reference_tokens: Iterable[Sequence[str]], n: int
) -> tuple[int, int, Counter[tuple[str, ...]], Counter[tuple[str, ...]]]:
    candidate_counts = ngram_counts(candidate_tokens, n)
    maximum_reference_counts: Counter[tuple[str, ...]] = Counter()
    for reference in reference_tokens:
        reference_counts = ngram_counts(reference, n)
        for gram, count in reference_counts.items():
            maximum_reference_counts[gram] = max(maximum_reference_counts[gram], count)
    matched = sum(min(count, maximum_reference_counts[gram]) for gram, count in candidate_counts.items())
    return matched, sum(candidate_counts.values()), candidate_counts, maximum_reference_counts


def analyze_ngrams(
    *,
    candidate: str | Sequence[str],
    references: Sequence[str | Sequence[str]],
    n_values: Sequence[int],
    tokenization: Tokenization,
) -> dict[str, Any]:
    if not references:
        raise ValueError("at least one reference is required")
    candidate_tokens = tokenize(candidate, tokenization)
    reference_tokens = [tokenize(reference, tokenization) for reference in references]
    analysis: list[dict[str, Any]] = []
    for n in sorted(set(n_values)):
        matched, total, candidate_counts, reference_counts = clipped_matches(
            candidate_tokens, reference_tokens, n
        )
        unmatched = [list(gram) for gram, count in candidate_counts.items()
                     if count > reference_counts[gram]]
        analysis.append({
            "n": n,
            "matched": matched,
            "total": total,
            "precision": matched / total if total else 0.0,
            "candidate_counts": [
                {"ngram": list(gram), "count": count}
                for gram, count in sorted(candidate_counts.items())
            ],
            "unmatched_ngrams": unmatched,
        })
    return {"candidate_tokens": candidate_tokens, "analysis": analysis}
