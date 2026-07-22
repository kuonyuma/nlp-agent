from pathlib import Path

import yaml


DATASET = Path(__file__).parents[1] / ".jbeval" / "suites" / "nlp-tool-routing-v1" / "dataset.yaml"
ORCHESTRATION_DATASET = Path(__file__).parents[1] / ".jbeval" / "suites" / "nlp-tool-orchestration-v1" / "dataset.yaml"
NLP_TOOLS = {
    "nlp_tfidf_analyzer",
    "nlp_precision_recall_curve",
    "nlp_precision_at_n",
    "nlp_ngram_analyzer",
    "nlp_bleu_score",
}


def test_tool_routing_dataset_has_valid_ids_expectations_and_broad_coverage():
    document = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    cases = document["cases"]
    ids = [case["id"] for case in cases]

    assert document["schema_version"] == "1.0"
    assert len(cases) >= 30
    assert len(ids) == len(set(ids))

    required_tools: set[str] = set()
    tags: set[str] = set()
    no_tool_cases = 0
    multi_tool_cases = 0
    for case in cases:
        expectation = case["expectation"]
        required = expectation.get("required_tools", [])
        forbidden = expectation.get("forbidden_tools", [])
        ordered = expectation.get("ordered_tools", [])
        used = set(required) | set(forbidden) | set(ordered)

        assert case["input"].strip()
        assert used <= NLP_TOOLS, f"{case['id']} references unknown tools: {used - NLP_TOOLS}"
        assert set(ordered) <= set(required)
        assert not (set(required) & set(forbidden))
        if expectation.get("expected_no_tool"):
            no_tool_cases += 1
            assert required == []
        if len(required) > 1:
            multi_tool_cases += 1
        required_tools.update(required)
        tags.update(case["tags"])

    assert required_tools == NLP_TOOLS
    assert no_tool_cases >= 8
    assert multi_tool_cases >= 3
    assert {"single-tool", "multi-tool", "no-tool", "critical", "forbidden"} <= tags


def test_orchestration_dataset_distinguishes_required_and_preferred_delegation():
    document = yaml.safe_load(ORCHESTRATION_DATASET.read_text(encoding="utf-8"))
    expectations = {case["id"]: case["expectation"] for case in document["cases"]}

    assert expectations["course-lab-two-independent-analyses"]["delegation_policy"] == "required"
    assert expectations["ngram-to-bleu-teaching-chain"]["delegation_policy"] == "preferred"
