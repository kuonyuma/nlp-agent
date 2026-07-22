import math

import pytest

from core.custom_tools import load_custom_tools
from core.nlp.bleu import score_bleu, score_corpus_bleu
from core.nlp.classification_metrics import precision_recall_curve
from core.nlp.ngrams import analyze_ngrams
from core.nlp.retrieval_metrics import precision_at_n
from core.nlp.tfidf import analyze_tfidf
from core.nlp_tools import TOOLS
from core.tool_config import CustomToolsConfig
from core.tool_runtime import ToolCatalog


def test_tfidf_uses_course_tf_and_base_ten_idf_formula():
    result = analyze_tfidf(
        documents=["alpha alpha beta", "beta gamma"],
        query="alpha",
        tokenization="whitespace",
    )

    alpha = result["documents"][0]["terms"]["alpha"]
    assert alpha["tf"] == pytest.approx(2 / 3)
    assert alpha["df"] == 1
    assert alpha["idf"] == pytest.approx(math.log10(2))
    assert alpha["tfidf"] == pytest.approx((2 / 3) * math.log10(2))
    assert result["results"][0]["document_id"] == "document-1"


def test_precision_recall_curve_returns_threshold_counts_and_best_f1():
    result = precision_recall_curve(labels=[1, 0, 1], scores=[0.9, 0.8, 0.2])

    assert result["points"][0] == {
        "threshold": 0.9,
        "tp": 1,
        "fp": 0,
        "fn": 1,
        "precision": 1.0,
        "recall": 0.5,
        "f1": pytest.approx(2 / 3),
    }
    assert result["best_f1"]["threshold"] == 0.2
    assert result["best_f1"]["f1"] == pytest.approx(0.8)


def test_precision_at_n_counts_missing_ranks_as_not_relevant():
    result = precision_at_n(
        ranked_results=[{"id": "one", "relevant": True}, {"id": "two", "relevant": False}],
        ks=[1, 3],
    )

    assert result["metrics"] == [
        {"k": 1, "relevant_count": 1, "precision_at_k": 1.0},
        {"k": 3, "relevant_count": 1, "precision_at_k": pytest.approx(1 / 3)},
    ]


def test_ngram_analysis_matches_the_course_bleu_example():
    result = analyze_ngrams(
        candidate="The guard arrived late because of the rain",
        references=["The guard arrived late because it was raining"],
        n_values=[1, 2, 3, 4],
        tokenization="whitespace",
    )

    assert [(item["n"], item["matched"], item["total"]) for item in result["analysis"]] == [
        (1, 5, 8),
        (2, 4, 7),
        (3, 3, 6),
        (4, 2, 5),
    ]


def test_bleu_uses_geometric_mean_and_course_brevity_penalty():
    result = score_bleu(
        candidate="The guard arrived late because of the rain",
        references=["The guard arrived late because it was raining"],
        max_n=4,
        tokenization="whitespace",
    )

    assert result["candidate_length"] == 8
    assert result["reference_length"] == 8
    assert result["brevity_penalty"] == 1.0
    assert result["geometric_mean"] == pytest.approx(
        ((5 / 8) * (4 / 7) * (3 / 6) * (2 / 5)) ** 0.25
    )
    assert result["bleu"] == result["geometric_mean"]


def test_corpus_bleu_aggregates_ngram_counts_across_sentences():
    result = score_corpus_bleu(
        candidates=["a b", "c"],
        references_per_candidate=[["a b"], ["d"]],
        max_n=1,
        tokenization="whitespace",
    )

    assert result["mode"] == "corpus"
    assert result["candidate_length"] == 3
    assert result["reference_length"] == 3
    assert result["modified_precisions"] == [
        {"n": 1, "matched": 2, "total": 3, "precision": pytest.approx(2 / 3)}
    ]
    assert result["bleu"] == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_all_nlp_tools_are_registered_as_low_risk_function_calling_tools():
    catalog = ToolCatalog()
    registered_names = load_custom_tools(
        CustomToolsConfig(modules=["core.nlp_tools"]), catalog
    )

    assert registered_names == [tool.name for tool in TOOLS]
    assert [tool.name for tool in TOOLS] == [
        "nlp_tfidf_analyzer",
        "nlp_precision_recall_curve",
        "nlp_precision_at_n",
        "nlp_ngram_analyzer",
        "nlp_bleu_score",
    ]
    for name in registered_names:
        descriptor = catalog.get(name)
        assert descriptor is not None
        assert descriptor.read_only is True
        assert descriptor.idempotent is True
        assert descriptor.concurrency_safe is True
        assert descriptor.category == "nlp"


def test_bleu_tool_description_prevents_redundant_ngram_calling():
    bleu = next(tool for tool in TOOLS if tool.name == "nlp_bleu_score")
    ngram = next(tool for tool in TOOLS if tool.name == "nlp_ngram_analyzer")

    assert "不要额外调用 nlp_ngram_analyzer" in bleu.description
    assert "仅在用户要求" in ngram.description


@pytest.mark.asyncio
async def test_precision_at_n_function_calling_tool_validates_and_returns_json_data():
    tool = next(tool for tool in TOOLS if tool.name == "nlp_precision_at_n").instantiate()

    result = await tool.ainvoke({
        "ranked_results": [{"id": "one", "relevant": True}],
        "ks": [1, 2],
    })

    assert result["metrics"][1]["precision_at_k"] == pytest.approx(0.5)
