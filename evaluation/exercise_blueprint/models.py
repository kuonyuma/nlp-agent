from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.learning import LearningContext


class StrictExerciseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExerciseSuite(StrictExerciseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class ExerciseBlueprintFixture(StrictExerciseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    topic_id: str = Field(min_length=1, max_length=64)
    topic_name: str = Field(min_length=1, max_length=120)
    knowledge_point_id: str = Field(min_length=1, max_length=64)
    knowledge_point_name: str = Field(min_length=1, max_length=120)
    knowledge_markdown: str = Field(min_length=1, max_length=20_000)
    instructions: str = Field(min_length=1, max_length=4_000)
    question_type: str = Field(min_length=1, max_length=80)
    rubric: list[dict[str, object]] = Field(min_length=1, max_length=30)
    status: Literal["enabled"] = "enabled"


class ExerciseStudentProfile(StrictExerciseModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    behavior_rules: list[str] = Field(min_length=1, max_length=20)


class ExerciseCase(StrictExerciseModel):
    id: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    student_profile: ExerciseStudentProfile
    learning_context: LearningContext
    start_message: str = Field(min_length=1, max_length=1_000)


class ExerciseDataset(StrictExerciseModel):
    schema_version: Literal["1.0"]
    suite: ExerciseSuite
    blueprint_path: str = Field(min_length=1)
    cases: list[ExerciseCase] = Field(min_length=5, max_length=5)
    blueprint: ExerciseBlueprintFixture


class StudentAnswer(StrictExerciseModel):
    content: str = Field(min_length=1, max_length=4_000)


class ExerciseTurnSnapshot(StrictExerciseModel):
    turn_number: int = Field(ge=1)
    turn_id: str = Field(min_length=1)
    chat_session_id: str = Field(min_length=1)
    exercise_session_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    exercise_status: str = Field(min_length=1)
    question: str = ""
    rubric_count: int = Field(default=0, ge=0)
    question_number: int = Field(default=0, ge=0)
    attempt: int = Field(default=0, ge=0)
    turn_status: str = Field(min_length=1)
    trace_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    student_reply: str = ""
    agent_reply: str = ""


class ExerciseRunSnapshot(StrictExerciseModel):
    case_id: str
    chat_session_id: str
    exercise_session_id: str
    blueprint_id: str
    turns: tuple[ExerciseTurnSnapshot, ...]


class ExerciseArchitectureResult(StrictExerciseModel):
    verdict: Literal["PASS", "FAIL"]
    failures: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
