from core.learning import LearningContext, default_progress


def test_learning_context_defaults_to_unselected_topic_beginner_and_explain_mode():
    context = LearningContext()

    assert context.topic_id is None
    assert context.topic_name == ""
    assert context.level == "beginner"
    assert context.mode == "explain"
    assert default_progress(context).objective == ""
