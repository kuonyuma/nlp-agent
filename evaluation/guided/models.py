from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.learning import LearningContext


class StrictGuidedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidedSuite(StrictGuidedModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class GuidedBlueprintFixture(StrictGuidedModel):
    """Versioned teacher-owned blueprint fixture; it is never a production default."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    topic_id: str = Field(min_length=1, max_length=64)
    topic_name: str = Field(min_length=1, max_length=120)
    knowledge_point_id: str = Field(min_length=1, max_length=64)
    knowledge_point_name: str = Field(min_length=1, max_length=120)
    knowledge_markdown: str = Field(min_length=1, max_length=20_000)
    guidance: str = Field(min_length=1, max_length=4_000)
    status: Literal["enabled"] = "enabled"


class StudentProfile(StrictGuidedModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    initial_goal: str = Field(min_length=1)
    hidden_misconceptions: list[str] = Field(default_factory=list, max_length=10)
    behavior_rules: list[str] = Field(default_factory=list, max_length=20)


class GuidedCase(StrictGuidedModel):
    id: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    student_profile: StudentProfile
    learning_context: LearningContext
    turn_budget: int = Field(ge=2, le=100)
    expected_architecture: dict[str, bool] = Field(default_factory=dict)


class GuidedDataset(StrictGuidedModel):
    schema_version: Literal["1.0"]
    suite: GuidedSuite
    blueprint_path: str = Field(min_length=1)
    defaults: dict = Field(default_factory=dict)
    cases: list[GuidedCase] = Field(min_length=1)
    blueprint: GuidedBlueprintFixture


class StudentReply(StrictGuidedModel):
    content: str = Field(min_length=1, max_length=4_000)
    action: Literal["answer", "misconception", "ask_hint", "terse", "off_topic", "complete"]
    stop: bool = False


class GuidedTurnSnapshot(StrictGuidedModel):
    turn_number: int = Field(ge=1)
    turn_id: str = Field(min_length=1)
    chat_session_id: str = Field(min_length=1)
    guided_session_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    turn_status: str = Field(min_length=1)
    progress_attempts: int = Field(ge=0)
    trace_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    student_reply: str = ""
    agent_reply: str = ""


class GuidedRunSnapshot(StrictGuidedModel):
    case_id: str
    chat_session_id: str
    guided_session_id: str
    blueprint_id: str
    turns: tuple[GuidedTurnSnapshot, ...]


class ArchitectureResult(StrictGuidedModel):
    verdict: Literal["PASS", "FAIL"]
    failures: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
