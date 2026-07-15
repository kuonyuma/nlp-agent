from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkerUsageSpec(BaseModel):
    total_tokens: int = 0
    tool_uses: int = 0
    duration_ms: int = 0


class WorkerArtifactSpec(BaseModel):
    kind: str
    name: str = ""
    uri: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerErrorSpec(BaseModel):
    category: Literal[
        "timeout",
        "model",
        "rate_limit",
        "network",
        "tool",
        "context",
        "budget",
        "cancelled",
        "internal",
    ]
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class WorkerTimingSpec(BaseModel):
    started_at: float
    completed_at: float
    duration_ms: int


class WorkerExecutionResultSpec(BaseModel):
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    summary: str
    output: str | None = None
    artifacts: list[WorkerArtifactSpec] = Field(default_factory=list)
    error: WorkerErrorSpec | None = None
    usage: WorkerUsageSpec = Field(default_factory=WorkerUsageSpec)
    timing: WorkerTimingSpec
    termination_reason: Literal[
        "completed",
        "cancelled",
        "timeout",
        "max_turns",
        "token_budget",
        "tool_budget",
        "unrecoverable_error",
        "retries_exhausted",
    ]
    attempt: int = 1


class WorkerNotificationSpec(BaseModel):
    task_id: str = Field(..., description="Worker 的唯一任务 ID")
    status: Literal["started", "completed", "failed", "cancelled", "timed_out"]
    summary: str
    result: str | None = None
    usage: WorkerUsageSpec | None = None
    join: bool = True
    execution: WorkerExecutionResultSpec | None = None
