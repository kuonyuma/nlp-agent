from __future__ import annotations

from typing import Protocol

from evaluation.guided.architecture import GuidedArchitectureJudge
from evaluation.guided.models import ArchitectureResult, GuidedBlueprintFixture, GuidedCase, GuidedRunSnapshot, StudentReply


class GuidedGatewayExecutor(Protocol):
    """Production-boundary adapter; implementations must use the existing Web Gateway."""

    async def start_case(self, *, case: GuidedCase, blueprint: GuidedBlueprintFixture) -> str: ...
    async def submit_student_reply(self, *, chat_session_id: str, content: str, case: GuidedCase) -> object: ...
    async def snapshot(self, *, chat_session_id: str, case_id: str) -> GuidedRunSnapshot: ...
    async def close_case(self, *, chat_session_id: str) -> None: ...


class StudentActor(Protocol):
    async def reply(self, *, profile, blueprint, transcript) -> StudentReply: ...


class GuidedEvaluationRunner:
    """Runs a real multi-turn conversation while retaining evaluator isolation."""

    def __init__(self, executor: GuidedGatewayExecutor, student: StudentActor, judge: GuidedArchitectureJudge | None = None) -> None:
        self.executor = executor
        self.student = student
        self.judge = judge or GuidedArchitectureJudge()

    async def run_case(self, *, case: GuidedCase, blueprint: GuidedBlueprintFixture) -> tuple[GuidedRunSnapshot, ArchitectureResult]:
        chat_session_id = await self.executor.start_case(case=case, blueprint=blueprint)
        transcript: list[dict[str, str]] = []
        try:
            for _ in range(case.turn_budget):
                student_reply = await self.student.reply(
                    profile=case.student_profile, blueprint=blueprint, transcript=transcript,
                )
                turn = await self.executor.submit_student_reply(
                    chat_session_id=chat_session_id, content=student_reply.content, case=case,
                )
                transcript.extend((
                    {"role": "student", "content": student_reply.content},
                    {"role": "teacher", "content": str(getattr(turn, "final_text", ""))},
                ))
                if student_reply.stop or bool(getattr(turn, "guided_completed", False)):
                    break
            snapshot = await self.executor.snapshot(chat_session_id=chat_session_id, case_id=case.id)
            return snapshot, self.judge.judge(snapshot)
        finally:
            # The adapter owns deletion only for explicitly tagged evaluation sessions.
            await self.executor.close_case(chat_session_id=chat_session_id)
