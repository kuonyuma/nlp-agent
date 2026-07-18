from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
