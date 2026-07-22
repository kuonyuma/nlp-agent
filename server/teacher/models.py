from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictTeacherModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeachingGoals(StrictTeacherModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    course_title: str = Field(default="NLP 基础课程", max_length=120)
    description: str = Field(default="", max_length=2_000)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    focus_topics: list[str] = Field(default_factory=list, max_length=30)
    target_level: Literal["beginner", "intermediate", "advanced"] = "beginner"


class UpdateTeachingGoals(StrictTeacherModel):
    course_title: str = Field(max_length=120)
    description: str = Field(default="", max_length=2_000)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    focus_topics: list[str] = Field(default_factory=list, max_length=30)
    target_level: Literal["beginner", "intermediate", "advanced"] = "beginner"


class KnowledgePoint(StrictTeacherModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    markdown: str = Field(default="", max_length=20_000)
    status: Literal["enabled", "disabled"] = "enabled"
    sort_order: int = Field(default=0, ge=0, le=10_000)


class CourseTopic(StrictTeacherModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)
    status: Literal["enabled", "disabled"] = "enabled"
    knowledge_points: list[KnowledgePoint] = Field(default_factory=list, max_length=100)


class ExerciseBlueprint(StrictTeacherModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    topic_id: str = Field(min_length=1, max_length=64)
    knowledge_point_id: str = Field(min_length=1, max_length=64)
    instructions: str = Field(min_length=1, max_length=4_000)
    question_type: str = Field(min_length=1, max_length=80)
    status: Literal["draft", "enabled", "disabled"] = "draft"
    rubric: list[dict[str, object]] = Field(default_factory=list, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_multi_question_shape(cls, value: object) -> object:
        """Read old persisted catalogues once; new responses never expose these fields."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "knowledge_point_id" not in data:
            points = data.pop("knowledge_point_ids", [])
            data["knowledge_point_id"] = points[0] if points else "legacy_unassigned"
        if "question_type" not in data:
            types = data.pop("question_types", [])
            data["question_type"] = types[0] if types else "简答"
        data.pop("question_count", None)
        # 蓝图不再绑定学习难度；保留读取旧目录的兼容性，并在下一次保存时清除该字段。
        data.pop("level", None)
        return data


class ReviewBlueprint(StrictTeacherModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    topic_id: str = Field(min_length=1, max_length=64)
    knowledge_point_id: str = Field(min_length=1, max_length=64)
    instructions: str = Field(min_length=1, max_length=4_000)
    exercise_blueprint_id: str | None = Field(default=None, max_length=64)
    status: Literal["draft", "enabled", "disabled"] = "draft"
    question_type: str = Field(min_length=1, max_length=80)
    rubric: list[dict[str, object]] = Field(default_factory=list, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_multi_question_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "knowledge_point_id" not in data:
            points = data.pop("knowledge_point_ids", [])
            data["knowledge_point_id"] = points[0] if points else "legacy_unassigned"
        if "question_type" not in data:
            types = data.pop("question_types", [])
            data["question_type"] = types[0] if types else "简答"
        data.pop("question_count", None)
        return data


class GuidedBlueprint(StrictTeacherModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    topic_id: str = Field(min_length=1, max_length=64)
    knowledge_point_id: str = Field(min_length=1, max_length=64)
    guidance: str = Field(min_length=1, max_length=4_000)
    status: Literal["draft", "enabled", "disabled"] = "draft"


class TeacherCatalog(StrictTeacherModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    topics: list[CourseTopic] = Field(default_factory=list, max_length=100)
    exercise_blueprints: list[ExerciseBlueprint] = Field(default_factory=list, max_length=100)
    review_blueprints: list[ReviewBlueprint] = Field(default_factory=list, max_length=100)
    guided_blueprints: list[GuidedBlueprint] = Field(default_factory=list, max_length=100)


class UpdateTeacherCatalog(StrictTeacherModel):
    topics: list[CourseTopic] = Field(default_factory=list, max_length=100)
    exercise_blueprints: list[ExerciseBlueprint] = Field(default_factory=list, max_length=100)
    review_blueprints: list[ReviewBlueprint] = Field(default_factory=list, max_length=100)
    guided_blueprints: list[GuidedBlueprint] = Field(default_factory=list, max_length=100)
