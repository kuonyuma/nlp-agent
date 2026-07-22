from __future__ import annotations

from evaluation.exercise_blueprint.http_executor import HttpExerciseGatewayExecutor
from evaluation.review_blueprint.models import ReviewBlueprintFixture, ReviewCase, ReviewRunSnapshot, ReviewTurnSnapshot


class HttpReviewGatewayExecutor(HttpExerciseGatewayExecutor):
    """Review adapter: shares safe HTTP/Trace polling, provisions review-only fixtures."""

    def __init__(self, web_url: str, *, workspace_id: str, suite_id: str = "review-blueprint-multiturn-v1", **kwargs) -> None:
        super().__init__(web_url, workspace_id=workspace_id, suite_id=suite_id, **kwargs)

    async def provision_fixture(self, blueprint: ReviewBlueprintFixture) -> None:
        client = await self._client()
        catalog_response = await client.get(f"/api/v1/teacher/catalog/{self.workspace_id}")
        catalog_response.raise_for_status()
        catalog = catalog_response.json()["catalog"]
        topics = [item for item in catalog.get("topics", []) if item.get("id") != blueprint.topic_id]
        topics.append({"id": blueprint.topic_id, "name": blueprint.topic_name, "description": "评测专用主题", "status": "enabled", "knowledge_points": [{"id": blueprint.knowledge_point_id, "name": blueprint.knowledge_point_name, "markdown": blueprint.knowledge_markdown, "status": "enabled", "sort_order": 0}]})
        reviews = [item for item in catalog.get("review_blueprints", []) if item.get("id") != blueprint.id]
        reviews.append({"id": blueprint.id, "name": blueprint.name, "topic_id": blueprint.topic_id, "knowledge_point_id": blueprint.knowledge_point_id, "instructions": blueprint.instructions, "question_type": blueprint.question_type, "rubric": blueprint.rubric, "status": "enabled"})
        saved = await client.put(f"/api/v1/teacher/catalog/{self.workspace_id}", json={"topics": topics, "exercise_blueprints": catalog.get("exercise_blueprints", []), "review_blueprints": reviews, "guided_blueprints": catalog.get("guided_blueprints", [])}, headers=self.headers)
        saved.raise_for_status()

    async def _assert_fixture_available(self, blueprint: ReviewBlueprintFixture) -> None:
        client = await self._client()
        response = await client.get(f"/api/v1/learning/catalog/{self.workspace_id}")
        response.raise_for_status()
        items = response.json()["catalog"].get("review_blueprints", [])
        if not any(item.get("id") == blueprint.id and item.get("status") == "enabled" for item in items):
            raise RuntimeError(f"Evaluation review blueprint {blueprint.id!r} is not enabled in {self.workspace_id!r}")

    async def start_case(self, *, case: ReviewCase, blueprint: ReviewBlueprintFixture) -> str:
        return await super().start_case(case=case, blueprint=blueprint)

    async def snapshot(self, *, chat_session_id: str, case_id: str) -> ReviewRunSnapshot:
        turns = self._turns.get(chat_session_id, [])
        if not turns:
            raise RuntimeError("review evaluation produced no turns")
        first = turns[0].get("exercise_state") or {}
        if not first.get("exercise_session_id") or not first.get("blueprint_id"):
            raise RuntimeError("Gateway did not return review exercise-session evidence")
        snapshots = []
        for number, turn in enumerate(turns, start=1):
            state, trace = turn.get("exercise_state") or {}, self._traces.get(str(turn["turn_id"])) or {}
            snapshots.append(ReviewTurnSnapshot(turn_number=number, turn_id=str(turn["turn_id"]), chat_session_id=str(turn["session_id"]), exercise_session_id=str(state.get("exercise_session_id") or "missing"), blueprint_id=str(state.get("blueprint_id") or "missing"), exercise_status=str(state.get("status") or "missing"), question=str(state.get("question") or ""), rubric_count=len(state.get("rubric") or []), question_number=int(state.get("question_number") or 0), attempt=int(state.get("attempt") or 0), turn_status=str(turn["status"]), trace_id=trace.get("trace_id"), input_tokens=int(trace.get("input_tokens") or 0), output_tokens=int(trace.get("output_tokens") or 0), total_tokens=int(trace.get("total_tokens") or 0), duration_ms=trace.get("duration_ms"), ttft_ms=trace.get("ttft_ms"), student_reply=str(turn.get("input_text") or ""), agent_reply=str(turn.get("final_text") or "")))
        return ReviewRunSnapshot(case_id=case_id, chat_session_id=chat_session_id, exercise_session_id=str(first["exercise_session_id"]), blueprint_id=str(first["blueprint_id"]), turns=tuple(snapshots))
