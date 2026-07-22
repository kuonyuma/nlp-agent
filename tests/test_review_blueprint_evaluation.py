from __future__ import annotations

from evaluation.review_blueprint.architecture import ReviewArchitectureJudge
from evaluation.review_blueprint.dataset import load_review_dataset
from evaluation.review_blueprint.models import ReviewRunSnapshot, ReviewTurnSnapshot


def test_review_dataset_loads_one_isolated_blueprint_and_five_review_cases():
    dataset, _ = load_review_dataset('.jbeval/suites/review-blueprint-multiturn-v1/dataset.yaml')
    assert dataset.suite.id == 'review-blueprint-multiturn-v1'
    assert len(dataset.cases) == 5
    assert all(case.learning_context.mode == 'review' for case in dataset.cases)


def test_review_judge_accepts_review_question_answer_grading_lifecycle():
    report = ReviewArchitectureJudge().judge(ReviewRunSnapshot(case_id='ok', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='review-bp', turns=(
        ReviewTurnSnapshot(turn_number=1, turn_id='turn-1', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='review-bp', exercise_status='awaiting_answer', question='回顾后解释 TF 与 IDF 的区别。', rubric_count=3, question_number=1, attempt=0, turn_status='completed', trace_id='trace-1'),
        ReviewTurnSnapshot(turn_number=2, turn_id='turn-2', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='review-bp', exercise_status='completed', rubric_count=3, question_number=1, attempt=1, turn_status='completed', trace_id='trace-2', agent_reply='复习反馈：TF 是局部词频，IDF 是全局稀有度。'),
    )))
    assert report.verdict == 'PASS'
    assert report.metrics['grading_completion_rate'] == 1


def test_review_judge_rejects_blueprint_change_and_incomplete_grading():
    report = ReviewArchitectureJudge().judge(ReviewRunSnapshot(case_id='broken', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='review-bp', turns=(
        ReviewTurnSnapshot(turn_number=1, turn_id='turn-1', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='review-bp', exercise_status='awaiting_answer', question='题目', rubric_count=1, question_number=1, turn_status='completed'),
        ReviewTurnSnapshot(turn_number=2, turn_id='turn-2', chat_session_id='chat-1', exercise_session_id='review-1', blueprint_id='wrong-bp', exercise_status='awaiting_answer', rubric_count=1, question_number=1, attempt=0, turn_status='completed'),
    )))
    assert report.verdict == 'FAIL'
    assert 'blueprint_changed' in report.failures
    assert 'grading_not_completed' in report.failures
