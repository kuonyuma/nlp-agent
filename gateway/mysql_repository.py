"""Synchronous GatewayRepository-compatible facade backed exclusively by MySQL.

The Gateway calls repository methods from worker threads, so this facade owns a
short SQLAlchemy transaction per command while the schema remains Alembic-only.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text

from core.learning import ExerciseState, LearningContext, LearningProgress
from gateway.contracts import GatewayEvent, GatewayEventType, TeachingConfigurationError, TurnRecord, TurnStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MySQLGatewayRepository:
    def __init__(self, url: str, *, knowledge_point_prompt_budget: int = 12_000) -> None:
        if not url.startswith("mysql+aiomysql://"):
            raise ValueError("MySQL Gateway repository requires mysql+aiomysql DSN")
        self._engine = create_engine(url.replace("mysql+aiomysql://", "mysql+pymysql://"), pool_pre_ping=True)
        self.knowledge_point_prompt_budget = max(1, knowledge_point_prompt_budget)

    def _row(self, turn_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as c:
            row = c.execute(text("SELECT * FROM nlp_turns WHERE id=:id"), {"id": turn_id}).mappings().first()
            return dict(row) if row else None

    def _record(self, row: dict[str, Any]) -> TurnRecord:
        state = row.get("learning_state_json") or {}
        return TurnRecord(turn_id=row["id"], session_id=row["conversation_id"], workspace_id=row["workspace_id"], user_id=row["user_id"], status=TurnStatus(row["status"]), input_text=row["input_text"], learning_context=LearningContext.model_validate(state["context"]) if state.get("context") else None, learning_progress=LearningProgress.model_validate(state["progress"]) if state.get("progress") else None, exercise_state=ExerciseState.model_validate(state["exercise"]) if state.get("exercise") else None, final_text=row.get("result_text"), error_kind=row.get("error_kind"), error_message=row.get("error_message"), created_at=row["created_at"], started_at=row.get("started_at"), completed_at=row.get("completed_at"))

    def create_turn(self, *, turn_id: str, session_id: str, workspace_id: str, user_id: str, input_text: str, idempotency_key: str | None, learning_context=None, learning_progress=None, exercise_state=None, **_: Any) -> tuple[TurnRecord, bool]:
        with self._engine.begin() as c:
            if idempotency_key:
                old = c.execute(text("SELECT * FROM nlp_turns WHERE user_id=:u AND conversation_id=:s AND idempotency_key=:k"), {"u": user_id, "s": session_id, "k": idempotency_key}).mappings().first()
                if old:
                    return self._record(dict(old)), True
            state = {"context": learning_context.model_dump(mode="json") if learning_context else None, "progress": learning_progress.model_dump(mode="json") if learning_progress else None, "exercise": exercise_state.model_dump(mode="json") if exercise_state else None}
            c.execute(text("INSERT INTO nlp_turns(id,conversation_id,workspace_id,user_id,status,input_text,learning_state_json,idempotency_key) VALUES(:id,:s,:w,:u,'accepted',:input,:state,:key)"), {"id": turn_id, "s": session_id, "w": workspace_id, "u": user_id, "input": input_text, "state": json.dumps(state), "key": idempotency_key})
        return self._record(self._row(turn_id) or {}), False

    def update_turn(self, turn_id: str, status: TurnStatus, *, final_text=None, error_kind=None, error_message=None, exercise_state=None) -> TurnRecord:
        terminal = status in {TurnStatus.COMPLETED, TurnStatus.FAILED, TurnStatus.CANCELLED, TurnStatus.INTERRUPTED}
        with self._engine.begin() as c:
            c.execute(text("UPDATE nlp_turns SET status=:status,result_text=:result,error_kind=:kind,error_message=:message,started_at=CASE WHEN :running='running' THEN UTC_TIMESTAMP(6) ELSE started_at END,completed_at=CASE WHEN :terminal=1 THEN UTC_TIMESTAMP(6) ELSE completed_at END WHERE id=:id"), {"status": status.value, "result": final_text, "kind": error_kind, "message": (error_message or "")[:1000] or None, "running": status.value, "terminal": int(terminal), "id": turn_id})
        row = self._row(turn_id)
        if row is None:
            raise KeyError(turn_id)
        return self._record(row)

    def get_turn(self, turn_id: str) -> TurnRecord | None:
        row = self._row(turn_id)
        return self._record(row) if row else None

    def active_turn_for_session(self, session_id: str, *, exclude_turn_id: str | None = None) -> TurnRecord | None:
        with self._engine.connect() as c:
            row = c.execute(text("SELECT * FROM nlp_turns WHERE conversation_id=:s AND status IN ('accepted','running') AND (:exclude IS NULL OR id<>:exclude) ORDER BY created_at DESC LIMIT 1"), {"s": session_id, "exclude": exclude_turn_id}).mappings().first()
        return self._record(dict(row)) if row else None

    def turn_for_idempotency(self, *, user_id: str, session_id: str, idempotency_key: str) -> TurnRecord | None:
        with self._engine.connect() as c:
            row = c.execute(text("SELECT * FROM nlp_turns WHERE user_id=:u AND conversation_id=:s AND idempotency_key=:k"), {"u": user_id, "s": session_id, "k": idempotency_key}).mappings().first()
        return self._record(dict(row)) if row else None

    def append_event(self, *, turn_id: str, session_id: str, event_type: GatewayEventType, payload=None) -> GatewayEvent:
        with self._engine.begin() as c:
            c.execute(text("SELECT id FROM nlp_turns WHERE id=:id FOR UPDATE"), {"id": turn_id})
            sequence = int(c.execute(text("SELECT COALESCE(MAX(sequence),0)+1 FROM nlp_turn_events WHERE turn_id=:id"), {"id": turn_id}).scalar_one())
            event_id = str(uuid.uuid4())
            c.execute(text("INSERT INTO nlp_turn_events(id,turn_id,sequence,claim_generation,event_type,payload_json) SELECT :event,:turn,:seq,claim_generation,:type,:payload FROM nlp_turns WHERE id=:turn"), {"event": event_id, "turn": turn_id, "seq": sequence, "type": event_type.value, "payload": json.dumps(payload or {})})
        return GatewayEvent(event_id=event_id, turn_id=turn_id, session_id=session_id, sequence=sequence, type=event_type, payload=payload or {})

    def events_after(self, turn_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[GatewayEvent]:
        with self._engine.connect() as c:
            rows = c.execute(text("SELECT e.*, t.conversation_id FROM nlp_turn_events e JOIN nlp_turns t ON t.id=e.turn_id WHERE e.turn_id=:id AND e.sequence>:after ORDER BY e.sequence LIMIT :limit"), {"id": turn_id, "after": max(0, after_sequence), "limit": min(max(1, limit), 2000)}).mappings().all()
        return [GatewayEvent(event_id=r["id"], turn_id=turn_id, session_id=r["conversation_id"], sequence=r["sequence"], type=GatewayEventType(r["event_type"]), created_at=r["created_at"], payload=r["payload_json"] or {}) for r in rows]

    def ensure_event(self, *, turn_id: str, session_id: str, event_type: GatewayEventType, payload=None) -> GatewayEvent:
        existing = next((e for e in self.events_after(turn_id, limit=2000) if e.type == event_type), None)
        return existing or self.append_event(turn_id=turn_id, session_id=session_id, event_type=event_type, payload=payload)

    def list_turns(self, session_id: str, *, limit: int = 100) -> list[TurnRecord]:
        with self._engine.connect() as c:
            rows = c.execute(text("SELECT * FROM nlp_turns WHERE conversation_id=:s ORDER BY created_at DESC LIMIT :limit"), {"s": session_id, "limit": min(max(1, limit), 500)}).mappings().all()
        return [self._record(dict(r)) for r in rows]

    def latest_learning_state(self, session_id: str):
        turns = [t for t in self.list_turns(session_id) if not (t.status == TurnStatus.FAILED and t.error_kind == "turn_conflict")]
        latest = turns[0] if turns else None
        return (latest.learning_context, latest.learning_progress, latest.exercise_state) if latest else (None, None, None)

    def teaching_topic(self, *_: Any): return None
    def _compat(self, namespace: str, aggregate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._engine.begin() as c:
            if payload is not None:
                c.execute(text("INSERT INTO nlp_gateway_compat(id,namespace,aggregate_id,payload_json) VALUES(UUID(),:n,:a,:p) ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json),revision=revision+1"), {"n": namespace, "a": aggregate_id, "p": json.dumps(payload, ensure_ascii=False, default=str)})
            row = c.execute(text("SELECT payload_json FROM nlp_gateway_compat WHERE namespace=:n AND aggregate_id=:a"), {"n": namespace, "a": aggregate_id}).scalar()
        return row if isinstance(row, dict) else (json.loads(row) if row else None)

    def get_teaching_catalog(self, workspace_id: str):
        catalog = self._compat("teaching", workspace_id) or {"workspace_id": workspace_id, "topics": [], "exercise_blueprints": [], "review_blueprints": [], "guided_blueprints": []}
        return {"workspace_id": workspace_id, "revision": int(catalog.get("revision", 0)), "catalog": catalog}

    def update_teaching_catalog(self, workspace_id: str, catalog: dict[str, Any]):
        current = self.get_teaching_catalog(workspace_id)
        revision = int(current["revision"]) + 1
        value = {**catalog, "workspace_id": workspace_id, "revision": revision}
        self._compat("teaching", workspace_id, value)
        return {"workspace_id": workspace_id, "revision": revision, "catalog": value}

    def teaching_topic(self, workspace_id: str, topic_id: str):
        catalog = self.get_teaching_catalog(workspace_id)["catalog"]
        topic = next((x for x in catalog.get("topics", []) if x.get("id") == topic_id and x.get("status", "enabled") == "enabled"), None)
        if topic is None: return None
        points = [x for x in topic.get("knowledge_points", []) if x.get("status", "enabled") == "enabled"]
        if sum(len(str(x.get("markdown") or x.get("name") or "")) for x in points) > self.knowledge_point_prompt_budget:
            raise TeachingConfigurationError(f"主题“{topic_id}”的知识点内容超过提示词预算")
        return {"id": topic_id, "name": topic.get("name", topic_id), "description": topic.get("description", ""), "knowledge_points": points}

    def select_guided_blueprint(self, *, workspace_id: str, topic_id: str):
        return next((x for x in self.get_teaching_catalog(workspace_id)["catalog"].get("guided_blueprints", []) if x.get("topic_id") == topic_id and x.get("status", "enabled") == "enabled"), None)

    def start_or_resume_guided_session(self, *, session_id: str, workspace_id: str, user_id: str, topic_id: str, first_message: str, guided_blueprint=None):
        key = f"{session_id}:{topic_id}"; current = self._compat("guided", key)
        if current and current.get("status") == "active": return current
        value = {"id": str(uuid.uuid4()), "session_id": session_id, "workspace_id": workspace_id, "user_id": user_id, "topic_id": topic_id, "status": "active", "attempts": 0, "objective": first_message, "guided_blueprint": guided_blueprint or {}}
        self._compat("guided", key, value); return value

    def advance_guided_session(self, guided_session_id: str, **changes: Any):
        with self._engine.connect() as c: key = c.execute(text("SELECT aggregate_id FROM nlp_gateway_compat WHERE namespace='guided' AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.id'))=:id LIMIT 1"), {"id": guided_session_id}).scalar()
        if not key: return changes
        value = self._compat("guided", key) or {}; value.update({k: v for k, v in changes.items() if v is not None}); self._compat("guided", key, value); return value
    def update_turn_guided_status(self, turn_id: str, *, status: str) -> None: return None
    def end_guided_sessions(self, *, session_id: str, status: str = "cancelled") -> int:
        with self._engine.connect() as c: keys = c.execute(text("SELECT aggregate_id FROM nlp_gateway_compat WHERE namespace='guided' AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.session_id'))=:s AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.status'))='active'"), {"s": session_id}).scalars().all()
        for key in keys: value = self._compat("guided", key) or {}; value["status"] = status; self._compat("guided", key, value)
        return len(keys)
    def expire_guided_sessions(self, *, session_id: str, idle_minutes: int = 30) -> int: return 0

    def start_exercise_session(self, *, session_id: str, workspace_id: str, user_id: str, topic_id: str, mode: str):
        blueprints = self.get_teaching_catalog(workspace_id)["catalog"].get("exercise_blueprints" if mode == "practice" else "review_blueprints", [])
        blueprint = next((x for x in blueprints if x.get("topic_id") == topic_id and x.get("status", "enabled") == "enabled"), None)
        if blueprint is None: return None
        value = {"id": str(uuid.uuid4()), "session_id": session_id, "workspace_id": workspace_id, "user_id": user_id, "topic_id": topic_id, "mode": mode, "status": "active", "blueprint_snapshot": blueprint, "attempts": []}
        self._compat("exercise", value["id"], value); return value

    def active_exercise_session(self, *, session_id: str, topic_id: str, mode: str):
        with self._engine.connect() as c: row = c.execute(text("SELECT payload_json FROM nlp_gateway_compat WHERE namespace='exercise' AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.session_id'))=:s AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.topic_id'))=:t AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.mode'))=:m AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.status'))='active' LIMIT 1"), {"s": session_id, "t": topic_id, "m": mode}).scalar()
        return row if isinstance(row, dict) else (json.loads(row) if row else None)
    def active_or_latest_exercise_session(self, **kwargs: Any): return self.active_exercise_session(**kwargs)
    def expire_exercise_sessions(self, **_: Any) -> int: return 0
    def end_exercise_sessions(self, *, session_id: str, status: str = "cancelled") -> int:
        return 0
    def exercise_state(self, exercise_session_id: str) -> ExerciseState:
        value = self._compat("exercise", exercise_session_id) or {}; question = value.get("question", "")
        return ExerciseState(question=question, rubric=value.get("rubric", []), attempt=len(value.get("attempts", [])), status="awaiting_answer" if question else "idle")
    def record_exercise_question(self, exercise_session_id: str, question: str):
        value = self._compat("exercise", exercise_session_id) or {}; value["question"] = question; value.setdefault("attempts", []); self._compat("exercise", exercise_session_id, value); return value
    def grade_exercise_answer(self, exercise_session_id: str, **result: Any):
        value = self._compat("exercise", exercise_session_id) or {}; value.setdefault("attempts", []).append(result); self._compat("exercise", exercise_session_id, value); return self.exercise_state(exercise_session_id)
    def get_user_settings(self, user_id: str): return self._compat("settings", user_id) or {}
    def update_user_settings(self, user_id: str, changes: dict[str, Any]):
        value = {**self.get_user_settings(user_id), **changes}; self._compat("settings", user_id, value); return value
    def delete_session(self, session_id: str) -> None: return None
    def latest_event_sequence(self, turn_id: str) -> int:
        with self._engine.connect() as c: return int(c.execute(text("SELECT COALESCE(MAX(sequence),0) FROM nlp_turn_events WHERE turn_id=:id"), {"id": turn_id}).scalar_one())
    def recover_interrupted(self): return []
    def prune_events(self, **_: Any): return {"compacted": 0, "capped": 0, "remaining": 0}
    def flush(self) -> None: return None
    def health(self):
        with self._engine.connect() as c: count = int(c.execute(text("SELECT COUNT(*) FROM nlp_turn_events")).scalar_one())
        return {"database": "mysql", "durable_events": count}
    def close(self) -> None: self._engine.dispose()
