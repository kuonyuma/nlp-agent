from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import httpx

from evaluation.guided.models import GuidedBlueprintFixture, GuidedCase, GuidedRunSnapshot, GuidedTurnSnapshot


_TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})


@dataclass(frozen=True)
class CompletedGuidedTurn:
    final_text: str
    guided_completed: bool = False


class HttpGuidedGatewayExecutor:
    """Gateway adapter for a pre-provisioned *evaluation-only* workspace.

    This adapter intentionally never creates or updates a teacher catalogue.
    Provision the fixture into an isolated workspace first, then pass that
    workspace through `--workspace` in the future CLI integration.  Each case
    is tagged in Gateway telemetry and its chat session is deleted on exit.
    """

    def __init__(
        self,
        web_url: str,
        *,
        workspace_id: str,
        suite_id: str = "guided-multiturn-v1",
        run_id: str | None = None,
        timeout_s: float = 120,
        monitor_url: str = "http://127.0.0.1:8766",
    ) -> None:
        if not workspace_id.startswith("evaluation-"):
            raise ValueError("guided live evaluation requires an evaluation-* workspace")
        self.web_url = web_url.rstrip("/")
        self.workspace_id = workspace_id
        self.suite_id = suite_id
        self.run_id = run_id or uuid.uuid4().hex
        self.timeout_s = timeout_s
        self.monitor_url = monitor_url.rstrip("/")
        self.client: httpx.AsyncClient | None = None
        self.headers: dict[str, str] = {}
        self._turns: dict[str, list[dict]] = {}
        self._trace_by_turn: dict[str, dict] = {}

    async def _trace_for_turn(self, turn_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.monitor_url, timeout=20) as monitor:
            auth = await monitor.post("/api/v1/auth/session", headers={"Origin": self.monitor_url})
            auth.raise_for_status()
            async with asyncio.timeout(self.timeout_s):
                delay = 0.25
                while True:
                    try:
                        traces = await monitor.get("/api/v1/observability/traces", params={"limit": 100})
                        traces.raise_for_status()
                        trace = next((item for item in traces.json()["items"] if item.get("turn_id") == turn_id and item.get("status") != "running"), None)
                        if trace is not None:
                            return trace
                        delay = 0.25
                    except (httpx.HTTPError, httpx.TimeoutException):
                        # Monitor is evidence collection, not the turn execution path.
                        # Back off when it is temporarily unavailable so a batch cannot
                        # turn a transient 502 into a CPU-bound polling storm.
                        delay = min(delay * 2, 5.0)
                    await asyncio.sleep(delay)

    async def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.web_url, timeout=20)
            response = await self.client.post("/api/v1/auth/session", headers={"Origin": self.web_url})
            response.raise_for_status()
            self.headers = {"Origin": self.web_url, "X-CSRF-Token": response.json()["csrf_token"]}
        return self.client

    async def _assert_fixture_available(self, blueprint: GuidedBlueprintFixture) -> None:
        client = await self._client()
        response = await client.get(f"/api/v1/learning/catalog/{self.workspace_id}")
        response.raise_for_status()
        configured = response.json()["catalog"].get("guided_blueprints", [])
        if not any(item.get("id") == blueprint.id and item.get("status") == "enabled" for item in configured):
            raise RuntimeError(
                f"Evaluation blueprint {blueprint.id!r} is not enabled in isolated workspace "
                f"{self.workspace_id!r}; this runner will not modify teacher catalogues."
            )

    async def provision_fixture(self, blueprint: GuidedBlueprintFixture) -> None:
        """Install only the fixture assets into the isolated evaluation workspace."""
        client = await self._client()
        response = await client.get(f"/api/v1/teacher/catalog/{self.workspace_id}")
        response.raise_for_status()
        catalog = response.json()["catalog"]
        topics = [item for item in catalog.get("topics", []) if item.get("id") != blueprint.topic_id]
        topics.append({
            "id": blueprint.topic_id, "name": blueprint.topic_name, "description": "评测专用主题",
            "status": "enabled", "knowledge_points": [{
                "id": blueprint.knowledge_point_id, "name": blueprint.knowledge_point_name,
                "markdown": blueprint.knowledge_markdown, "status": "enabled", "sort_order": 0,
            }],
        })
        guided = [item for item in catalog.get("guided_blueprints", []) if item.get("id") != blueprint.id]
        guided.append({
            "id": blueprint.id, "name": blueprint.name, "topic_id": blueprint.topic_id,
            "knowledge_point_id": blueprint.knowledge_point_id, "guidance": blueprint.guidance,
            "status": "enabled",
        })
        saved = await client.put(
            f"/api/v1/teacher/catalog/{self.workspace_id}",
            json={
                "topics": topics,
                "exercise_blueprints": catalog.get("exercise_blueprints", []),
                "review_blueprints": catalog.get("review_blueprints", []),
                "guided_blueprints": guided,
            },
            headers=self.headers,
        )
        saved.raise_for_status()

    async def start_case(self, *, case: GuidedCase, blueprint: GuidedBlueprintFixture) -> str:
        await self._assert_fixture_available(blueprint)
        client = await self._client()
        response = await client.post("/api/v1/sessions", json={"workspace_id": self.workspace_id}, headers=self.headers)
        response.raise_for_status()
        session_id = str(response.json()["session_id"])
        self._turns[session_id] = []
        return session_id

    async def submit_student_reply(self, *, chat_session_id: str, content: str, case: GuidedCase) -> CompletedGuidedTurn:
        client = await self._client()
        accepted = await client.post(
            "/api/v1/chat/turns",
            json={
                "session_id": chat_session_id,
                "content": content,
                "idempotency_key": f"guided-eval-{uuid.uuid4().hex}",
                "learning_context": case.learning_context.model_dump(mode="json"),
                "evaluation": {"run_id": self.run_id, "suite_id": self.suite_id, "case_id": case.id},
            },
            headers=self.headers,
        )
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
                        raise RuntimeError(
                            f"guided turn {turn_id} ended as {turn['status']}: "
                            f"{turn.get('error_kind') or 'unknown'}: {turn.get('error_message') or ''}"
                        )
                    self._trace_by_turn[turn_id] = await self._trace_for_turn(turn_id)
                    return CompletedGuidedTurn(
                        final_text=str(turn.get("final_text") or ""),
                        guided_completed=(turn.get("guided_session") or {}).get("status") == "completed",
                    )
                await asyncio.sleep(0.1)

    async def snapshot(self, *, chat_session_id: str, case_id: str) -> GuidedRunSnapshot:
        turns = self._turns.get(chat_session_id, [])
        if not turns:
            raise RuntimeError("guided evaluation produced no turns")
        first_ref = turns[0].get("guided_session") or {}
        if not first_ref.get("id"):
            raise RuntimeError("Gateway did not return guided_session evidence")
        snapshots = tuple(
            GuidedTurnSnapshot(
                turn_number=index,
                turn_id=str(turn["turn_id"]),
                chat_session_id=str(turn["session_id"]),
                guided_session_id=str((turn.get("guided_session") or {}).get("id") or "missing"),
                blueprint_id=str((turn.get("guided_session") or {}).get("blueprint_id") or "missing"),
                turn_status=str(turn["status"]),
                progress_attempts=int((turn.get("guided_session") or {}).get("attempts", 0)),
                trace_id=(self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("trace_id"),
                input_tokens=int((self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("input_tokens") or 0),
                output_tokens=int((self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("output_tokens") or 0),
                total_tokens=int((self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("total_tokens") or 0),
                duration_ms=(self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("duration_ms"),
                ttft_ms=(self._trace_by_turn.get(str(turn["turn_id"])) or {}).get("ttft_ms"),
                student_reply=str(turn.get("input_text") or ""),
                agent_reply=str(turn.get("final_text") or ""),
            )
            for index, turn in enumerate(turns, start=1)
        )
        return GuidedRunSnapshot(
            case_id=case_id,
            chat_session_id=chat_session_id,
            guided_session_id=str(first_ref["id"]),
            blueprint_id=str(first_ref.get("blueprint_id") or "missing"),
            turns=snapshots,
        )

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
