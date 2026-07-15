from typing import Literal

from pydantic import BaseModel, Field


class WorkerUsageSpec(BaseModel):
    total_tokens: int = 0
    tool_uses: int = 0
    duration_ms: int = 0


class WorkerNotificationSpec(BaseModel):
    task_id: str = Field(..., description="Worker 的唯一任务 ID")
    status: Literal["started", "completed", "failed", "killed"]
    summary: str
    result: str | None = None
    usage: WorkerUsageSpec | None = None
    join: bool = True
