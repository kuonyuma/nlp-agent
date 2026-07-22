"""Course-aligned TF-IDF calculations using base-ten logarithms."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from core.nlp.tokenization import Tokenization, tokenize


def analyze_tfidf(
    *, documents: Sequence[str], query: str, tokenization: Tokenization
) -> dict[str, Any]:
    if not documents:
        raise ValueError("at least one document is required")
    tokenized_documents = [tokenize(document, tokenization) for document in documents]
    document_frequency: Counter[str] = Counter(
        term for tokens in tokenized_documents for term in set(tokens)
    )
    corpus_size = len(tokenized_documents)
    idf = {term: math.log10(corpus_size / frequency) for term, frequency in document_frequency.items()}
    document_data: list[dict[str, Any]] = []
    vectors: list[dict[str, float]] = []
    for index, tokens in enumerate(tokenized_documents, start=1):
        counts = Counter(tokens)
        total = len(tokens)
        terms = {
            term: {
                "tf": count / total if total else 0.0,
                "df": document_frequency[term],
                "idf": idf[term],
                "tfidf": (count / total if total else 0.0) * idf[term],
            }
            for term, count in sorted(counts.items())
        }
        vectors.append({term: values["tfidf"] for term, values in terms.items()})
        document_data.append({"document_id": f"document-{index}", "tokens": tokens, "terms": terms})
    query_counts = Counter(tokenize(query, tokenization))
    query_total = sum(query_counts.values())
    query_vector = {
        term: (count / query_total) * idf[term]
        for term, count in query_counts.items()
        if term in idf and query_total
    }
    results = [
        {"document_id": f"document-{index}", "score": _cosine_similarity(query_vector, vector)}
        for index, vector in enumerate(vectors, start=1)
    ]
    results.sort(key=lambda item: (-item["score"], item["document_id"]))
    return {
        "formula": "tf=n_i,j/sum_k(n_k,j); idf=lg(|D|/df); tfidf=tf*idf",
        "documents": document_data,
        "query_tokens": list(query_counts.elements()),
        "results": results,
    }


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
