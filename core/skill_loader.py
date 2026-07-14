import os
from typing import Dict

import yaml
from pydantic import BaseModel, Field

from utils.logger import get_logger


logger = get_logger("nlp_agent.skill_loader")


class MarkdownSkillSpec(BaseModel):
    name: str
    when_to_use: str
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_sop: str


class SkillLoader:
    """加载通用基础工具和 Markdown Skill。"""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = skills_dir
        self.skills: Dict[str, MarkdownSkillSpec] = {}
        self.base_tools: Dict[str, str] = {}
        self._load_base_tools()
        self._load_skills()

    def _load_base_tools(self) -> None:
        path = os.path.join(self.skills_dir, "base_tools.yaml")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as file:
            self.base_tools = yaml.safe_load(file) or {}

    def _load_skills(self) -> None:
        os.makedirs(self.skills_dir, exist_ok=True)
        candidates = []
        for root, _, files in os.walk(self.skills_dir):
            for filename in files:
                if filename == "SKILL.md" or (
                    root == self.skills_dir and filename.endswith(".md")
                ):
                    candidates.append(os.path.join(root, filename))
        for path in candidates:
            skill = self._parse(path)
            if skill:
                self.skills[skill.name] = skill

    def _parse(self, path: str) -> MarkdownSkillSpec | None:
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            if not content.startswith("---"):
                return None
            _, raw_metadata, body = content.split("---", 2)
            metadata = yaml.safe_load(raw_metadata) or {}
            usage = metadata.get("when_to_use") or metadata.get("description")
            if not metadata.get("name") or not usage:
                return None
            return MarkdownSkillSpec(
                name=metadata["name"],
                when_to_use=usage,
                allowed_tools=metadata.get("allowed_tools", []),
                prompt_sop=body.strip(),
            )
        except Exception as error:
            logger.warning("Skill 加载失败", path=path, error=str(error))
            return None

    def get_planner_listing(self) -> str:
        lines = ["【可用 Skills】"]
        if self.skills:
            lines.extend(
                f"- {name}: {skill.when_to_use}"
                for name, skill in sorted(self.skills.items())
            )
        else:
            lines.append("- 当前未配置领域 Skill")
        lines.append("\n【可分配给 Worker 的通用工具】")
        lines.extend(
            f"- {name}: {description}"
            for name, description in self.base_tools.items()
        )
        return "\n".join(lines)

    def is_skill(self, agent_name: str) -> bool:
        return agent_name in self.skills

    def is_base_tool(self, agent_name: str) -> bool:
        return agent_name in self.base_tools


skill_loader = SkillLoader()

