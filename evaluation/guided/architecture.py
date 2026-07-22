from __future__ import annotations

from evaluation.guided.models import ArchitectureResult, GuidedRunSnapshot


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class GuidedArchitectureJudge:
    """Deterministic checks over persisted per-turn guided-session snapshots."""

    def judge(self, snapshot: GuidedRunSnapshot) -> ArchitectureResult:
        failures: list[str] = []
        turns = snapshot.turns
        if not turns:
            failures.append("no_turns")
        if any(turn.chat_session_id != snapshot.chat_session_id for turn in turns):
            failures.append("chat_session_changed")
        if any(turn.guided_session_id != snapshot.guided_session_id for turn in turns):
            failures.append("guided_session_changed")
        if any(turn.blueprint_id != snapshot.blueprint_id for turn in turns):
            failures.append("blueprint_changed")
        if any(turn.turn_status not in _TERMINAL_STATUSES for turn in turns):
            failures.append("turn_not_terminal")
        if any(turn.turn_status != "completed" for turn in turns):
            failures.append("turn_not_completed")
        attempts = [turn.progress_attempts for turn in turns]
        if any(next_value <= value for value, next_value in zip(attempts, attempts[1:])):
            failures.append("progress_attempt_not_increasing")
        metrics = {
            "turn_count": float(len(turns)),
            "completed_turn_rate": (
                sum(turn.turn_status == "completed" for turn in turns) / len(turns)
                if turns else 0.0
            ),
            "trace_capture_rate": (
                sum(turn.trace_id is not None for turn in turns) / len(turns)
                if turns else 0.0
            ),
            "total_tokens": float(sum(turn.total_tokens for turn in turns)),
            "max_turn_tokens": float(max((turn.total_tokens for turn in turns), default=0)),
            "max_turn_latency_ms": float(max((turn.duration_ms or 0 for turn in turns), default=0)),
        }
        return ArchitectureResult(
            verdict="FAIL" if failures else "PASS",
            failures=tuple(failures),
            metrics=metrics,
        )
