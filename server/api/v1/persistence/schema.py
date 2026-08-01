"""Transport-neutral command and result schemas for MySQL master data."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CourseCatalogCommand(BaseModel):
    workspace_id: str
    expected_revision: int
    topics: list[dict[str, Any]] = Field(default_factory=list)
    blueprints: list[dict[str, Any]] = Field(default_factory=list)
    change_summary: str = ""


class CourseCatalogResult(BaseModel):
    workspace_id: str
    revision: int
    topics: list[dict[str, Any]]
    blueprints: list[dict[str, Any]]


class CreateConversationCommand(BaseModel):
    id: str
    workspace_id: str
    owner_user_id: str
    title: str = ""


class CreateTurnCommand(BaseModel):
    id: str
    conversation_id: str
    workspace_id: str
    user_id: str
    input_text: str
    idempotency_key: str | None = None
    learning_state: dict[str, Any] | None = None


class CreateExerciseSessionCommand(BaseModel):
    id: str
    conversation_id: str
    workspace_id: str
    user_id: str
    topic_id: str
    mode: str
    blueprint_snapshot: dict[str, Any]


class AppendTurnEventCommand(BaseModel):
    turn_id: str
    claim_generation: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
