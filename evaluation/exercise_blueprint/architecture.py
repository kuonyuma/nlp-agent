from __future__ import annotations

from evaluation.exercise_blueprint.models import ExerciseArchitectureResult, ExerciseRunSnapshot


class ExerciseArchitectureJudge:
    """Deterministic checks over public TurnRecord and Monitor evidence."""

    def judge(self, snapshot: ExerciseRunSnapshot) -> ExerciseArchitectureResult:
        failures: list[str] = []
        turns = snapshot.turns
        if len(turns) != 2:
            failures.append("unexpected_turn_count")
        if any(turn.turn_status != "completed" for turn in turns):
            failures.append("turn_not_completed")
        if any(turn.chat_session_id != snapshot.chat_session_id for turn in turns):
            failures.append("chat_session_changed")
        if any(turn.exercise_session_id != snapshot.exercise_session_id for turn in turns):
            failures.append("exercise_session_changed")
        if any(turn.blueprint_id != snapshot.blueprint_id for turn in turns):
            failures.append("blueprint_changed")
        if turns:
            first = turns[0]
            if first.exercise_status != "awaiting_answer" or not first.question:
                failures.append("question_not_persisted")
            if first.question_number != 1 or first.rubric_count < 1:
                failures.append("question_or_rubric_invalid")
        if len(turns) > 1:
            graded = turns[1]
            if graded.exercise_status != "completed":
                failures.append("grading_not_completed")
            if graded.attempt != 1:
                failures.append("grading_attempt_invalid")
            if not graded.agent_reply.strip():
                failures.append("grading_feedback_missing")
        metrics = {
            "turn_count": float(len(turns)),
            "completed_turn_rate": sum(turn.turn_status == "completed" for turn in turns) / len(turns) if turns else 0.0,
            "trace_capture_rate": sum(turn.trace_id is not None for turn in turns) / len(turns) if turns else 0.0,
            "question_generation_rate": float(bool(turns and turns[0].question)),
            "grading_completion_rate": float(len(turns) > 1 and turns[1].exercise_status == "completed"),
            "rubric_count": float(turns[0].rubric_count if turns else 0),
            "total_tokens": float(sum(turn.total_tokens for turn in turns)),
            "input_tokens": float(sum(turn.input_tokens for turn in turns)),
            "output_tokens": float(sum(turn.output_tokens for turn in turns)),
            "max_turn_tokens": float(max((turn.total_tokens for turn in turns), default=0)),
            "max_turn_latency_ms": float(max((turn.duration_ms or 0 for turn in turns), default=0)),
            "grading_latency_ms": float(turns[1].duration_ms or 0) if len(turns) > 1 else 0.0,
        }
        return ExerciseArchitectureResult(verdict="FAIL" if failures else "PASS", failures=tuple(failures), metrics=metrics)
