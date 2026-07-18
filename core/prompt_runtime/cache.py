"""Small mtime-aware cache for editable Markdown prompt templates."""

from __future__ import annotations

from pathlib import Path


class PromptTemplateCache:
    def __init__(self) -> None:
        self._entries: dict[Path, tuple[int, str]] = {}

    def read(self, path: Path) -> str:
        stat = path.stat()
        cached = self._entries.get(path)
        if cached is not None and cached[0] == stat.st_mtime_ns:
            return cached[1]
        content = path.read_text(encoding="utf-8")
        self._entries[path] = (stat.st_mtime_ns, content)
        return content

    def clear(self) -> None:
        self._entries.clear()
