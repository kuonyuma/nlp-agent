"""Writable Developer control plane for Tool policies, Skills, and MCP servers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from core.runtime_config import BASE_DIR, load_runtime_overrides, save_runtime_overrides
from core.tool_config import CustomToolsConfig, MCPServerConfig, ToolPoliciesConfig, WorkerProfileSpec
from core.tool_runtime import ToolCatalog


_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class DeveloperConfigurationError(ValueError):
    pass


def _require_name(value: str, label: str) -> str:
    if not _NAME.fullmatch(value):
        raise DeveloperConfigurationError(f"{label} must contain only letters, digits, _ or -")
    return value


def _section(name: str) -> dict[str, Any]:
    overrides = load_runtime_overrides()
    value = overrides.setdefault(name, {})
    if not isinstance(value, dict):
        raise DeveloperConfigurationError(f"invalid persisted {name} override")
    return overrides


async def reload_runtime(*, reload_mcp: bool = False, reload_skills: bool = False) -> dict[str, Any]:
    """Refresh config consumers. Existing Worker grants intentionally stay immutable."""
    from configs.settings import settings
    from core.skill_loader import skill_loader
    from core.tool_registry import physical_tool_manager

    settings._config = __import__("core.runtime_config", fromlist=["load_runtime_config"]).load_runtime_config()
    physical_tool_manager.refresh_config()
    if reload_skills:
        skill_loader.profiles = physical_tool_manager.config.worker_profiles
        skill_loader.reload()
    if reload_mcp:
        await physical_tool_manager.runtime.start_mcp(physical_tool_manager.config.tools.mcp_servers)
    return {
        "catalog_revision": physical_tool_manager.catalog_revision,
        "mcp_reloaded": reload_mcp,
        "skills_reloaded": reload_skills,
        "restart_required": False,
    }


async def update_tool_policies(policies: dict[str, Any]) -> dict[str, Any]:
    validated = ToolPoliciesConfig.model_validate(policies)
    overrides = _section("tools")
    overrides["tools"]["policies"] = validated.model_dump(mode="json")
    save_runtime_overrides(overrides)
    return await reload_runtime()


async def update_custom_tools(custom: dict[str, Any]) -> dict[str, Any]:
    """Persist extension discovery config; changing Python imports requires a safe restart."""
    validated = CustomToolsConfig.model_validate(custom)
    overrides = _section("tools")
    overrides["tools"]["custom"] = validated.model_dump(mode="json")
    save_runtime_overrides(overrides)
    await reload_runtime()
    return {"restart_required": True, "reason": "custom Python tool modules reload on next runtime start"}


async def upsert_mcp_server(name: str, config: dict[str, Any]) -> dict[str, Any]:
    name = _require_name(name, "MCP server name")
    validated = MCPServerConfig.model_validate(config)
    await test_mcp_server(name, validated.model_dump(mode="json"))
    overrides = _section("tools")
    servers = overrides["tools"].setdefault("mcp_servers", {})
    servers[name] = validated.model_dump(mode="json")
    save_runtime_overrides(overrides)
    result = await reload_runtime(reload_mcp=True)
    return {**result, "server": name}


async def delete_mcp_server(name: str) -> dict[str, Any]:
    name = _require_name(name, "MCP server name")
    overrides = _section("tools")
    servers = overrides["tools"].setdefault("mcp_servers", {})
    servers.pop(name, None)
    save_runtime_overrides(overrides)
    result = await reload_runtime(reload_mcp=True)
    return {**result, "server": name}


async def test_mcp_server(name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Connect/discover through an isolated catalog; no trial tools leak into the live runtime."""
    name = _require_name(name, "MCP server name")
    validated = MCPServerConfig.model_validate(config)
    from core.mcp_runtime import MCPRuntime

    catalog = ToolCatalog()
    runtime = MCPRuntime(catalog)
    try:
        await runtime.connect_all({name: validated})
        return {"ok": True, "server": name, "tools": list(catalog.names())}
    finally:
        await runtime.close()


def _skill_path(name: str) -> Path:
    return BASE_DIR / ".data" / "skills" / _require_name(name, "Skill name") / "SKILL.md"


async def upsert_skill(name: str, content: str) -> dict[str, Any]:
    path = _skill_path(name)
    if len(content.encode("utf-8")) > 200_000:
        raise DeveloperConfigurationError("Skill content exceeds 200KB")
    if not content.lstrip().startswith("---"):
        raise DeveloperConfigurationError("Skill must begin with YAML frontmatter")
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", content, re.DOTALL)
    if match is None:
        raise DeveloperConfigurationError("Skill YAML frontmatter is incomplete")
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict) or metadata.get("name") != name:
        raise DeveloperConfigurationError("Skill frontmatter name must match the Skill name")
    if not isinstance(metadata.get("description") or metadata.get("when_to_use"), str):
        raise DeveloperConfigurationError("Skill frontmatter requires description or when_to_use")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    await reload_runtime(reload_skills=True)
    return {"name": name, "path": path.relative_to(BASE_DIR).as_posix()}


def read_skill(name: str) -> dict[str, Any]:
    name = _require_name(name, "Skill name")
    from core.skill_loader import skill_loader

    skill = skill_loader.skills.get(name)
    if skill is None:
        raise FileNotFoundError(name)
    path = skill.path
    return {"name": name, "content": path.read_text(encoding="utf-8")}


async def delete_skill(name: str) -> dict[str, Any]:
    path = _skill_path(name)
    if path.exists():
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    await reload_runtime(reload_skills=True)
    return {"name": name}


async def upsert_worker_profile(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    name = _require_name(name, "Worker profile name")
    validated = WorkerProfileSpec.model_validate({"name": name, **profile})
    overrides = _section("worker_profiles")
    overrides["worker_profiles"][name] = validated.model_dump(mode="json", exclude={"name"})
    save_runtime_overrides(overrides)
    return {**await reload_runtime(reload_skills=True), "profile": name}


async def delete_worker_profile(name: str) -> dict[str, Any]:
    name = _require_name(name, "Worker profile name")
    overrides = _section("worker_profiles")
    overrides["worker_profiles"].pop(name, None)
    save_runtime_overrides(overrides)
    return {**await reload_runtime(reload_skills=True), "profile": name}
