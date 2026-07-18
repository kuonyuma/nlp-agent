from server.teacher.analytics import analyze, clean_question


def row(turn_id: str, question: str, *, session: str = "s1", error: str | None = None):
    return {
        "turn_id": turn_id, "session_id": session, "workspace_id": "default",
        "user_id": "student", "status": "failed" if error else "completed",
        "input_text": question, "error_kind": error, "created_at": "2026-01-01T00:00:00Z",
    }


def test_learning_context_is_removed_and_declared_difficulty_is_used():
    raw = '<!-- nlp-learning-context:{"topic":"Transformer","level":"advanced"} -->\n什么是自注意力？'
    question, context = clean_question(raw)
    assert question == "什么是自注意力？"
    assert context["level"] == "advanced"
    result = analyze([row("t1", raw)])
    assert result["questions"][0]["topic"] == "Transformer 与注意力"
    assert result["questions"][0]["difficulty"] == "advanced"


def test_frequent_questions_weak_topics_and_distributions_are_derived():
    rows = [
        row("t1", "Transformer 和 RNN 有什么区别？"),
        row("t2", "Transformer 和 RNN 有什么区别？", session="s2"),
        row("t3", "如何用 Python 实现 self-attention？", error="TimeoutError"),
    ]
    result = analyze(rows)
    assert result["summary"]["questions"] == 3
    assert result["frequent_questions"][0]["count"] == 2
    assert result["weak_topics"][0]["topic"] == "Transformer 与注意力"
    assert result["difficulty_distribution"]
