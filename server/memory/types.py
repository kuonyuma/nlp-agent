"""Validated contracts for scoped, file-based memory."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MEMORY_TYPES = ["profile", "preference", "project", "feedback", "decision", "goal"]


class MemoryScopeKind(str, Enum):
    USER = "user"
    WORKSPACE = "workspace"


class MemoryRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    max_injection_tokens: int = Field(default=6_000, ge=500, le=32_000)
    max_topics: int = Field(default=12, ge=0, le=100)
    recent_archive_tokens: int = Field(default=2_000, ge=0, le=16_000)
    curate_after_archives: int = Field(default=8, ge=1, le=100)


class MemoryTopicHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    name: str
    memory_type: str
    description: str = ""
    scope: MemoryScopeKind
    updated_at: float = 0


class MemoryArchiveRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    cursor: int = Field(ge=1)
    source_id: str
    workspace_id: str
    user_id: str
    session_id: str
    agent_id: str = "coordinator"
    summary: str = Field(min_length=1, max_length=64_000)
    source_message_ids: tuple[str, ...] = ()
    created_at: float = Field(default_factory=time.time)


class MemoryCuratorOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "update", "delete", "ignore"]
    scope: MemoryScopeKind
    filename: str
    memory_type: str
    description: str = Field(max_length=500)
    content: str = Field(default="", max_length=16_000)
    evidence_archive_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=1_000)
    confidence: float = Field(default=0, ge=0, le=1)

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, value: str) -> str:
        if value not in MEMORY_TYPES:
            raise ValueError(f"memory type must be one of: {', '.join(MEMORY_TYPES)}")
        return value


class MemoryCurationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[MemoryCuratorOperation] = Field(default_factory=list, max_length=50)


def is_valid_memory_type(memory_type: str) -> bool:
    return memory_type in MEMORY_TYPES


def get_type_display_name(memory_type: str) -> str:
    return {
        "profile": "User profile",
        "preference": "Preference",
        "project": "Project context",
        "feedback": "Feedback and correction",
        "decision": "Durable decision",
        "goal": "Ongoing goal",
    }.get(memory_type, memory_type)
