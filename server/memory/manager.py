import os
import re
import time
from typing import Any

from server.memory.types import MEMORY_TYPES, get_type_display_name, is_valid_memory_type


MEMORY_DIR = os.path.join(".data", "memory")
INDEX_FILENAME = "MEMORY.md"
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000
HEADER_SCAN_LINES = 30
STALE_WARN_DAYS = 30


class MemoryManager:
    def __init__(self, memory_dir: str = MEMORY_DIR):
        self.memory_dir = memory_dir
        os.makedirs(self.memory_dir, exist_ok=True)

    def load_memory_index(self) -> str:
        path = os.path.join(self.memory_dir, INDEX_FILENAME)
        if not os.path.exists(path):
            return "# Long-term Memory Index\n\n当前没有已保存的长期记忆。\n"
        with open(path, "r", encoding="utf-8") as file:
            return file.read()

    def read_memory_topic(self, filename: str) -> str:
        path = os.path.join(self.memory_dir, os.path.basename(filename))
        if not os.path.exists(path):
            raise FileNotFoundError(f"未找到记忆文件：{filename}")
        with open(path, "r", encoding="utf-8") as file:
            return file.read()

    def save_memory_topic(
        self,
        filename: str,
        content: str,
        memory_type: str,
        description: str,
    ) -> str:
        if not is_valid_memory_type(memory_type):
            raise ValueError(f"记忆类型必须是：{', '.join(MEMORY_TYPES)}")
        clean_name = os.path.basename(filename)
        if not clean_name.endswith(".md"):
            clean_name += ".md"
        if clean_name == INDEX_FILENAME:
            raise ValueError("不能直接覆盖记忆索引")

        name = os.path.splitext(clean_name)[0]
        document = (
            f"---\nname: {name}\ndescription: {description}\n"
            f"type: {memory_type}\n---\n\n{content.strip()}\n"
        )
        with open(os.path.join(self.memory_dir, clean_name), "w", encoding="utf-8") as file:
            file.write(document)
        self._regenerate_index()
        return clean_name

    def delete_memory_topic(self, filename: str) -> None:
        clean_name = os.path.basename(filename)
        if clean_name == INDEX_FILENAME:
            raise ValueError("不能删除记忆索引")
        os.remove(os.path.join(self.memory_dir, clean_name))
        self._regenerate_index()

    def scan_memory_headers(self) -> list[dict[str, Any]]:
        memories = []
        for filename in os.listdir(self.memory_dir):
            if not filename.endswith(".md") or filename == INDEX_FILENAME:
                continue
            path = os.path.join(self.memory_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    head = "".join(next(file, "") for _ in range(HEADER_SCAN_LINES))
                frontmatter, preview = self._parse_frontmatter(head)
                memories.append(
                    {
                        "filename": filename,
                        "name": frontmatter.get("name", os.path.splitext(filename)[0]),
                        "type": frontmatter.get("type", "unknown"),
                        "description": frontmatter.get("description", ""),
                        "preview": preview[:200],
                        "mtime": os.path.getmtime(path),
                    }
                )
            except OSError:
                continue
        return sorted(memories, key=lambda item: item["mtime"], reverse=True)

    def check_stale_memories(self, days: int = STALE_WARN_DAYS) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {**item, "age_days": int((now - item["mtime"]) / 86400)}
            for item in self.scan_memory_headers()
            if now - item["mtime"] > days * 86400
        ]

    @staticmethod
    def _parse_frontmatter(document: str) -> tuple[dict[str, str], str]:
        normalized = document.replace("\r\n", "\n")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", normalized, re.DOTALL)
        if not match:
            return {}, document.strip()
        raw_frontmatter, body = match.groups()
        frontmatter = {}
        for line in raw_frontmatter.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
        return frontmatter, body.strip()

    def _regenerate_index(self) -> None:
        lines = ["# Long-term Memory Index", ""]
        for item in self.scan_memory_headers():
            label = get_type_display_name(item["type"])
            lines.append(f"- **[{label}]** `{item['filename']}` — {item['description']}")
        if len(lines) == 2:
            lines.append("当前没有已保存的长期记忆。")

        content = "\n".join(lines) + "\n"
        encoded = content.encode("utf-8")
        if len(lines) > MAX_INDEX_LINES or len(encoded) > MAX_INDEX_BYTES:
            content = "\n".join(lines[:MAX_INDEX_LINES])
            content = content.encode("utf-8")[:MAX_INDEX_BYTES].decode("utf-8", errors="ignore")
            content += "\n\n> 索引已达到上限，较旧条目可能未显示。\n"
        with open(os.path.join(self.memory_dir, INDEX_FILENAME), "w", encoding="utf-8") as file:
            file.write(content)

