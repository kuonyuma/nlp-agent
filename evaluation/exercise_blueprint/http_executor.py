from __future__ import annotations

import asyncio
import uuid

import httpx

from evaluation.exercise_blueprint.models import ExerciseBlueprintFixture, ExerciseCase, ExerciseRunSnapshot, ExerciseTurnSnapshot


_TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})


class HttpExerciseGatewayExecutor:
    """Real Gateway adapter restricted to an evaluation-* workspace."""

    def __init__(self, web_url: str, *, workspace_id: str, suite_id: str = "exercise-blueprint-multiturn-v1", run_id: str | None = None, timeout_s: float = 120, monitor_url: str = "http://127.0.0.1:8766") -> None:
        if not workspace_id.startswith("evaluation-"):
            raise ValueError("exercise live evaluation requires an evaluation-* workspace")
        self.web_url, self.workspace_id, self.suite_id = web_url.rstrip("/"), workspace_id, suite_id
        self.run_id, self.timeout_s, self.monitor_url = run_id or uuid.uuid4().hex, timeout_s, monitor_url.rstrip("/")
        self.client: httpx.AsyncClient | None = None
        self.headers: dict[str, str] = {}
        self._turns: dict[str, list[dict]] = {}
        self._traces: dict[str, dict] = {}

    async def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.web_url, timeout=20)
            auth = await self.client.post("/api/v1/auth/session", headers={"Origin": self.web_url})
            auth.raise_for_status()
            self.headers = {"Origin": self.web_url, "X-CSRF-Token": auth.json()["csrf_token"]}
        return self.client

    async def _trace_for_turn(self, turn_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.monitor_url, timeout=20) as monitor:
            auth = await monitor.post("/api/v1/auth/session", headers={"Origin": self.monitor_url})
            auth.raise_for_status()
            async with asyncio.timeout(self.timeout_s):
                delay = 0.25
                while True:
                    try:
                        response = await monitor.get("/api/v1/observability/traces", params={"limit": 100})
                        response.raise_for_status()
                        trace = next((item for item in response.json()["items"] if item.get("turn_id") == turn_id and item.get("status") != "running"), None)
                        if trace is not None:
                            return trace
                        delay = 0.25
                    except httpx.HTTPError:
                        delay = min(delay * 2, 5.0)
                    await asyncio.sleep(delay)

    async def provision_fixture(self, blueprint: ExerciseBlueprintFixture) -> None:
        client = await self._client()
        catalog_response = await client.get(f"/api/v1/teacher/catalog/{self.workspace_id}")
        catalog_response.raise_for_status()
        catalog = catalog_response.json()["catalog"]
        topics = [item for item in catalog.get("topics", []) if item.get("id") != blueprint.topic_id]
        topics.append({"id": blueprint.topic_id, "name": blueprint.topic_name, "description": "评测专用主题", "status": "enabled", "knowledge_points": [{"id": blueprint.knowledge_point_id, "name": blueprint.knowledge_point_name, "markdown": blueprint.knowledge_markdown, "status": "enabled", "sort_order": 0}]})
        exercises = [item for item in catalog.get("exercise_blueprints", []) if item.get("id") != blueprint.id]
        exercises.append({"id": blueprint.id, "name": blueprint.name, "topic_id": blueprint.topic_id, "knowledge_point_id": blueprint.knowledge_point_id, "instructions": blueprint.instructions, "question_type": blueprint.question_type, "rubric": blueprint.rubric, "status": "enabled"})
        saved = await client.put(f"/api/v1/teacher/catalog/{self.workspace_id}", json={"topics": topics, "exercise_blueprints": exercises, "review_blueprints": catalog.get("review_blueprints", []), "guided_blueprints": catalog.get("guided_blueprints", [])}, headers=self.headers)
        saved.raise_for_status()

    async def _assert_fixture_available(self, blueprint: ExerciseBlueprintFixture) -> None:
        client = await self._client()
        response = await client.get(f"/api/v1/learning/catalog/{self.workspace_id}")
        response.raise_for_status()
        items = response.json()["catalog"].get("exercise_blueprints", [])
        if not any(item.get("id") == blueprint.id and item.get("status") == "enabled" for item in items):
            raise RuntimeError(f"Evaluation exercise blueprint {blueprint.id!r} is not enabled in {self.workspace_id!r}")

    async def start_case(self, *, case: ExerciseCase, blueprint: ExerciseBlueprintFixture) -> str:
        await self._assert_fixture_available(blueprint)
        client = await self._client()
        response = await client.post("/api/v1/sessions", json={"workspace_id": self.workspace_id}, headers=self.headers)
        response.raise_for_status()
        session_id = str(response.json()["session_id"])
        self._turns[session_id] = []
        return session_id

    async def submit(self, *, chat_session_id: str, content: str, case: ExerciseCase) -> dict:
        client = await self._client()
        accepted = await client.post("/api/v1/chat/turns", json={"session_id": chat_session_id, "content": content, "idempotency_key": f"exercise-eval-{uuid.uuid4().hex}", "learning_context": case.learning_context.model_dump(mode="json"), "evaluation": {"run_id": self.run_id, "suite_id": self.suite_id, "case_id": case.id}}, headers=self.headers)
        accepted.raise_for_status()
        turn_id = str(accepted.json()["turn_id"])
        async with asyncio.timeout(self.timeout_s):
            while True:
                response = await client.get(f"/api/v1/chat/turns/{turn_id}")
                response.raise_for_status()
                turn = response.json()
                if turn["status"] in _TERMINAL:
                    self._turns[chat_session_id].append(turn)
                    if turn["status"] != "completed":
                        raise RuntimeError(f"exercise turn {turn_id} ended as {turn['status']}: {turn.get('error_kind') or 'unknown'}")
                    self._traces[turn_id] = await self._trace_for_turn(turn_id)
                    return turn
                await asyncio.sleep(0.1)

    async def snapshot(self, *, chat_session_id: str, case_id: str) -> ExerciseRunSnapshot:
        turns = self._turns.get(chat_session_id, [])
        if not turns:
            raise RuntimeError("exercise evaluation produced no turns")
        first = turns[0].get("exercise_state") or {}
        if not first.get("exercise_session_id") or not first.get("blueprint_id"):
            raise RuntimeError("Gateway did not return exercise session evidence")
        snapshots = []
        for number, turn in enumerate(turns, start=1):
            state, trace = turn.get("exercise_state") or {}, self._traces.get(str(turn["turn_id"])) or {}
            snapshots.append(ExerciseTurnSnapshot(turn_number=number, turn_id=str(turn["turn_id"]), chat_session_id=str(turn["session_id"]), exercise_session_id=str(state.get("exercise_session_id") or "missing"), blueprint_id=str(state.get("blueprint_id") or "missing"), exercise_status=str(state.get("status") or "missing"), question=str(state.get("question") or ""), rubric_count=len(state.get("rubric") or []), question_number=int(state.get("question_number") or 0), attempt=int(state.get("attempt") or 0), turn_status=str(turn["status"]), trace_id=trace.get("trace_id"), input_tokens=int(trace.get("input_tokens") or 0), output_tokens=int(trace.get("output_tokens") or 0), total_tokens=int(trace.get("total_tokens") or 0), duration_ms=trace.get("duration_ms"), ttft_ms=trace.get("ttft_ms"), student_reply=str(turn.get("input_text") or ""), agent_reply=str(turn.get("final_text") or "")))
        return ExerciseRunSnapshot(case_id=case_id, chat_session_id=chat_session_id, exercise_session_id=str(first["exercise_session_id"]), blueprint_id=str(first["blueprint_id"]), turns=tuple(snapshots))

    async def close_case(self, *, chat_session_id: str) -> None:
        try:
            client = await self._client()
            response = await client.delete(f"/api/v1/sessions/{chat_session_id}", headers=self.headers)
            response.raise_for_status()
        finally:
            self._turns.pop(chat_session_id, None)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
