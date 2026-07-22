from __future__ import annotations

from evaluation.exercise_blueprint.architecture import ExerciseArchitectureJudge
from evaluation.exercise_blueprint.dataset import load_exercise_dataset
from evaluation.exercise_blueprint.models import ExerciseRunSnapshot, ExerciseTurnSnapshot


def test_exercise_dataset_loads_one_isolated_blueprint_and_five_cases():
    dataset, _ = load_exercise_dataset('.jbeval/suites/exercise-blueprint-multiturn-v1/dataset.yaml')
    assert dataset.suite.id == 'exercise-blueprint-multiturn-v1'
    assert len(dataset.cases) == 5
    assert dataset.blueprint.question_type == '简答题'
    assert all(case.learning_context.mode == 'practice' for case in dataset.cases)


def test_exercise_judge_accepts_question_answer_grading_lifecycle():
    report = ExerciseArchitectureJudge().judge(ExerciseRunSnapshot(case_id='ok', chat_session_id='chat-1', exercise_session_id='exercise-1', blueprint_id='blueprint-1', turns=(
        ExerciseTurnSnapshot(turn_number=1, turn_id='turn-1', chat_session_id='chat-1', exercise_session_id='exercise-1', blueprint_id='blueprint-1', exercise_status='awaiting_answer', question='说明 TF 与 IDF 的区别。', rubric_count=3, question_number=1, attempt=0, turn_status='completed', trace_id='trace-1'),
        ExerciseTurnSnapshot(turn_number=2, turn_id='turn-2', chat_session_id='chat-1', exercise_session_id='exercise-1', blueprint_id='blueprint-1', exercise_status='completed', rubric_count=3, question_number=1, attempt=1, turn_status='completed', trace_id='trace-2', agent_reply='反馈：TF 是词频，IDF 是稀有度。'),
    )))
    assert report.verdict == 'PASS'
    assert report.metrics['grading_completion_rate'] == 1


def test_exercise_judge_rejects_session_change_and_missing_grading_completion():
    report = ExerciseArchitectureJudge().judge(ExerciseRunSnapshot(case_id='broken', chat_session_id='chat-1', exercise_session_id='exercise-1', blueprint_id='blueprint-1', turns=(
        ExerciseTurnSnapshot(turn_number=1, turn_id='turn-1', chat_session_id='chat-1', exercise_session_id='exercise-1', blueprint_id='blueprint-1', exercise_status='awaiting_answer', question='题目', rubric_count=1, question_number=1, turn_status='completed'),
        ExerciseTurnSnapshot(turn_number=2, turn_id='turn-2', chat_session_id='chat-1', exercise_session_id='exercise-2', blueprint_id='blueprint-1', exercise_status='awaiting_answer', rubric_count=1, question_number=1, attempt=0, turn_status='completed'),
    )))
    assert report.verdict == 'FAIL'
    assert 'exercise_session_changed' in report.failures
    assert 'grading_not_completed' in report.failures
