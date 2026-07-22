from __future__ import annotations

from evaluation.review_blueprint.architecture import ReviewArchitectureJudge
from evaluation.review_blueprint.models import ReviewArchitectureResult, ReviewBlueprintFixture, ReviewCase, ReviewRunSnapshot


class ReviewEvaluationRunner:
    def __init__(self, executor, student, judge: ReviewArchitectureJudge | None = None) -> None:
        self.executor, self.student, self.judge = executor, student, judge or ReviewArchitectureJudge()

    async def run_case(self, *, case: ReviewCase, blueprint: ReviewBlueprintFixture) -> tuple[ReviewRunSnapshot, ReviewArchitectureResult]:
        chat_session_id = await self.executor.start_case(case=case, blueprint=blueprint)
        try:
            question_turn = await self.executor.submit(chat_session_id=chat_session_id, content=case.start_message, case=case)
            question = str((question_turn.get("exercise_state") or {}).get("question") or question_turn.get("final_text") or "")
            answer = await self.student.answer(profile=case.student_profile, blueprint=blueprint, question=question)
            await self.executor.submit(chat_session_id=chat_session_id, content=answer.content, case=case)
            snapshot = await self.executor.snapshot(chat_session_id=chat_session_id, case_id=case.id)
            return snapshot, self.judge.judge(snapshot)
        finally:
            await self.executor.close_case(chat_session_id=chat_session_id)
