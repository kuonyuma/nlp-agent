"""Strict Pydantic-v2 configuration for tools, policies, profiles, and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.runtime_config import load_runtime_config
from core.tool_runtime import ToolRisk, ToolScope


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleToolPolicy(StrictConfigModel):
    allowed_tools: set[str] = Field(default_factory=set)
    allowed_capabilities: set[str] = Field(default_factory=set)
    denied_tools: set[str] = Field(default_factory=set)
    denied_capabilities: set[str] = Field(default_factory=set)


class ToolPoliciesConfig(StrictConfigModel):
    coordinator: RoleToolPolicy = Field(
        default_factory=lambda: RoleToolPolicy(
            allowed_tools={
                "spawn_worker",
                "send_message",
                "TaskStop",
                "read_local_file",
                "get_current_time",
            },
            allowed_capabilities={"context.manage"},
            denied_capabilities={"business.write"},
        )
    )
    worker: RoleToolPolicy = Field(
        default_factory=lambda: RoleToolPolicy(
            denied_capabilities={"runtime.control", "worker.manage"}
        )
    )


class CustomToolManifest(StrictConfigModel):
    """Required metadata contract for one custom-tool provider."""

    id: str
    version: str
    category: str = "general"
    prompt_priority: int = Field(default=100, ge=-1000, le=1000)
    scopes: set[ToolScope] = Field(default_factory=lambda: {ToolScope.WORKER})
    capabilities: set[str] = Field(default_factory=set)
    risk: ToolRisk = ToolRisk.MEDIUM
    enabled: bool = True

    @field_validator("id", "version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("manifest id and version cannot be blank")
        return value


class CustomToolsConfig(StrictConfigModel):
    modules: list[str] = Field(default_factory=list)
    entrypoint_group: str = "nlp_agent.tools"
    manifests: dict[str, CustomToolManifest] = Field(default_factory=dict)


class MCPServerConfig(StrictConfigModel):
    transport: Literal["stdio", "sse", "streamable_http"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    allow_private_network: bool = False
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])
    read_only_tools: set[str] = Field(default_factory=set)
    idempotent_tools: set[str] = Field(default_factory=set)
    high_risk_tools: set[str] = Field(default_factory=set)
    session_exclusive_tools: set[str] = Field(default_factory=set)
    global_exclusive_tools: set[str] = Field(default_factory=set)
    retry_attempts: int = Field(default=2, ge=1, le=5)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    timeout_s: float = Field(default=30.0, gt=0, le=1800)
    scopes: set[ToolScope] = Field(default_factory=lambda: {ToolScope.WORKER})

    @model_validator(mode="after")
    def validate_transport(self) -> "MCPServerConfig":
        transport = self.transport
        if transport is None:
            transport = "stdio" if self.command else "streamable_http" if self.url else None
            object.__setattr__(self, "transport", transport)
        if transport == "stdio" and not self.command:
            raise ValueError("stdio MCP server requires command")
        if transport in {"sse", "streamable_http"} and not self.url:
            raise ValueError(f"{transport} MCP server requires url")
        return self


class ToolRuntimeConfig(StrictConfigModel):
    policies: ToolPoliciesConfig = Field(default_factory=ToolPoliciesConfig)
    custom: CustomToolsConfig = Field(default_factory=CustomToolsConfig)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class WorkerProfileSpec(StrictConfigModel):
    name: str
    description: str = ""
    model: str | None = None
    skills: list[str] = Field(default_factory=list)
    capabilities: set[str] = Field(default_factory=set)
    allowed_tools: set[str] = Field(default_factory=set)
    denied_tools: set[str] = Field(default_factory=set)


class AgentRuntimeConfig(StrictConfigModel):
    tools: ToolRuntimeConfig = Field(default_factory=ToolRuntimeConfig)
    worker_profiles: dict[str, WorkerProfileSpec] = Field(default_factory=dict)


def load_agent_runtime_config(path: Path | None = None) -> AgentRuntimeConfig:
    if path is None:
        raw = load_runtime_config()
    else:
        import yaml

        with path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    payload = {
        "tools": raw.get("tools", {}),
        "worker_profiles": raw.get("worker_profiles", {}),
    }
    profiles = payload["worker_profiles"]
    if isinstance(profiles, dict):
        payload["worker_profiles"] = {
            name: ({"name": name, **value} if isinstance(value, dict) else value)
            for name, value in profiles.items()
        }
    return AgentRuntimeConfig.model_validate(payload)
