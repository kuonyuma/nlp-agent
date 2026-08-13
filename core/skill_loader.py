"""Pydantic-v2 Skill catalog and Worker Profile resolution."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.tool_config import WorkerProfileSpec, load_agent_runtime_config
from utils.logger import get_logger


logger = get_logger("nlp_agent.skill_loader")
_FRONTMATTER = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)


class SkillRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bins: list[str] = Field(default_factory=list)
    env: list[str] = Field(default_factory=list)


class MarkdownSkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    allowed_tools: set[str] = Field(default_factory=set)
    capabilities: set[str] = Field(default_factory=set)
    requires: SkillRequirements = Field(default_factory=SkillRequirements)
    always: bool = False
    prompt_sop: str
    path: Path
    source: str

    @property
    def when_to_use(self) -> str:
        return self.description

    def availability(self) -> tuple[bool, list[str]]:
        missing = [f"bin:{name}" for name in self.requires.bins if not shutil.which(name)]
        missing.extend(f"env:{name}" for name in self.requires.env if not os.environ.get(name))
        return not missing, missing


class ResolvedWorkerProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    model: str | None = None
    execution_mode: str = "react"
    requires_native_search: bool = False
    inherit_tool_policy: bool = True
    skills: tuple[str, ...] = ()
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    allowed_tools: frozenset[str] = Field(default_factory=frozenset)
    denied_tools: frozenset[str] = Field(default_factory=frozenset)
    system_prompt: str = ""


class SkillLoader:
    """Load project skills with optional workspace overrides and validate profiles."""

    def __init__(
        self,
        skills_dir: str | Path | None = None,
        workspace_skills_dir: str | Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parent.parent
        self.skills_dir = Path(skills_dir) if skills_dir else root / "skills"
        self.workspace_skills_dir = (
            Path(workspace_skills_dir) if workspace_skills_dir else root / ".data" / "skills"
        )
        self.skills: dict[str, MarkdownSkillSpec] = {}
        self.base_tools: dict[str, str] = {}
        self.profiles: dict[str, WorkerProfileSpec] = load_agent_runtime_config().worker_profiles
        self.reload()

    def reload(self) -> None:
        self.skills = {}
        self._load_base_tools()
        self._load_dir(self.skills_dir, "project", overwrite=False)
        self._load_dir(self.workspace_skills_dir, "workspace", overwrite=True)

    def _load_base_tools(self) -> None:
        path = self.skills_dir / "base_tools.yaml"
        if not path.exists():
            self.base_tools = {}
            return
        with path.open("r", encoding="utf-8") as file:
            payload = yaml.safe_load(file) or {}
        if not isinstance(payload, dict) or not all(
            isinstance(name, str) and isinstance(description, str)
            for name, description in payload.items()
        ):
            raise ValueError("skills/base_tools.yaml must be a string-to-string mapping")
        self.base_tools = payload

    def _load_dir(self, root: Path, source: str, *, overwrite: bool) -> None:
        if not root.exists():
            return
        candidates = sorted(root.rglob("SKILL.md"))
        candidates.extend(sorted(path for path in root.glob("*.md") if path.name != "SKILL.md"))
        for path in candidates:
            skill = self._parse(path, source)
            if skill is None:
                continue
            if skill.name in self.skills and not overwrite:
                raise ValueError(f"duplicate Skill name: {skill.name}")
            if skill.name in self.skills:
                logger.info("Workspace Skill overrides project Skill", skill=skill.name)
            self.skills[skill.name] = skill

    def _parse(self, path: Path, source: str) -> MarkdownSkillSpec | None:
        try:
            content = path.read_text(encoding="utf-8")
            match = _FRONTMATTER.match(content)
            if match is None:
                raise ValueError("missing YAML frontmatter")
            metadata = yaml.safe_load(match.group(1)) or {}
            nested = metadata.get("metadata", {})
            if isinstance(nested, str):
                nested = yaml.safe_load(nested) or {}
            nlp_metadata = nested.get("nlp_agent", {}) if isinstance(nested, dict) else {}
            requires = metadata.get("requires") or nlp_metadata.get("requires") or {}
            return MarkdownSkillSpec.model_validate(
                {
                    "name": metadata.get("name"),
                    "description": metadata.get("description") or metadata.get("when_to_use"),
                    "allowed_tools": metadata.get("allowed_tools", []),
                    "capabilities": metadata.get("capabilities", []),
                    "requires": requires,
                    "always": metadata.get("always", False) or nlp_metadata.get("always", False),
                    "prompt_sop": content[match.end() :].strip(),
                    "path": path,
                    "source": source,
                }
            )
        except Exception as error:
            logger.warning("Skill load failed", path=str(path), error=str(error))
            return None

    def validate_tool_references(self, available_tools: set[str]) -> None:
        errors: list[str] = []
        for name in self.base_tools:
            if name not in available_tools:
                errors.append(f"base tool {name!r} is not registered")
        for skill in self.skills.values():
            unknown = skill.allowed_tools.difference(available_tools)
            if unknown:
                errors.append(
                    f"Skill {skill.name!r} references unknown tools: {', '.join(sorted(unknown))}"
                )
        if errors:
            raise ValueError("; ".join(errors))

    def resolve_profile(self, name: str) -> ResolvedWorkerProfile:
        configured = self.profiles.get(name)
        if configured is not None:
            skill_names = configured.skills
            description = configured.description
            model = configured.model
            execution_mode = configured.execution_mode
            requires_native_search = configured.requires_native_search
            inherit_tool_policy = configured.inherit_tool_policy
            allowed_tools = set(configured.allowed_tools)
            capabilities = set(configured.capabilities)
            denied_tools = set(configured.denied_tools)
        elif name in self.skills:
            skill_names = [name]
            description = self.skills[name].description
            model = None
            execution_mode = "react"
            requires_native_search = False
            inherit_tool_policy = True
            allowed_tools = set()
            capabilities = set()
            denied_tools = set()
        elif name in self.base_tools:
            return ResolvedWorkerProfile(
                name=name,
                description=self.base_tools[name],
                allowed_tools=frozenset({name}),
                system_prompt="你是一个精确的工具执行 Worker。直接使用授权工具完成任务。",
            )
        else:
            raise ValueError(f"unknown Worker Profile, Skill, or base tool: {name}")

        prompts: list[str] = []
        for skill_name in skill_names:
            skill = self.skills.get(skill_name)
            if skill is None:
                raise ValueError(f"Worker Profile {name!r} references unknown Skill {skill_name!r}")
            available, missing = skill.availability()
            if not available:
                raise ValueError(
                    f"Skill {skill_name!r} is unavailable: {', '.join(missing)}"
                )
            allowed_tools.update(skill.allowed_tools)
            capabilities.update(skill.capabilities)
            prompts.append(f"## Skill: {skill.name}\n\n{skill.prompt_sop}")
        return ResolvedWorkerProfile(
            name=name,
            description=description,
            model=model,
            execution_mode=execution_mode,
            requires_native_search=requires_native_search,
            inherit_tool_policy=inherit_tool_policy,
            skills=tuple(skill_names),
            capabilities=frozenset(capabilities),
            allowed_tools=frozenset(allowed_tools),
            denied_tools=frozenset(denied_tools),
            system_prompt="\n\n---\n\n".join(prompts),
        )

    def get_planner_listing(self) -> str:
        lines = ["【可用 Worker Profiles / Skills】"]
        names = sorted(set(self.profiles).union(self.skills))
        for name in names:
            if name in self.profiles:
                description = self.profiles[name].description or name
                lines.append(f"- {name}: {description}")
            else:
                skill = self.skills[name]
                available, missing = skill.availability()
                suffix = "" if available else f"（不可用：{', '.join(missing)}）"
                lines.append(f"- {name}: {skill.description}{suffix}")
        if not names:
            lines.append("- 当前未配置 Worker Profile 或领域 Skill")
        lines.append("\n【可作为单工具 Worker 的基础工具】")
        lines.extend(
            f"- {name}: {description}" for name, description in sorted(self.base_tools.items())
        )
        return "\n".join(lines)

    def is_skill(self, agent_name: str) -> bool:
        return agent_name in self.skills

    def is_base_tool(self, agent_name: str) -> bool:
        return agent_name in self.base_tools


skill_loader = SkillLoader()
