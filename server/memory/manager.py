"""Scoped local memory store with one auditable root directory."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from core.session_context import SessionContext
from server.memory.types import (
    MemoryArchiveRecord,
    MemoryCuratorOperation,
    MemoryScopeKind,
    get_type_display_name,
    is_valid_memory_type,
)
from utils.tokens import rough_token_count_estimation


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = str(_PROJECT_ROOT / ".data" / "memory")
INDEX_FILENAME = "MEMORY.md"
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000
HEADER_SCAN_LINES = 30
STALE_WARN_DAYS = 30
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|passwd|private[_-]?key)\s*[:=]"
)


def _scope_key(*parts: str) -> str:
    raw = "\0".join(parts).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _truncate_to_tokens(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if rough_token_count_estimation(text) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if rough_token_count_estimation(text[:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "\n...[memory truncated]"


class MemoryManager:
    """Read and write user/workspace memory under a single ``.data/memory`` root."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(
        self,
        context: SessionContext | str | Path | None = None,
        memory_dir: str | Path | None = None,
    ) -> None:
        # Backwards compatible with the old ``MemoryManager(memory_dir)`` call.
        if isinstance(context, (str, Path)) and memory_dir is None:
            memory_dir = context
            context = None
        self.context = context or SessionContext(session_id="default_session")
        self.root = Path(memory_dir or MEMORY_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.user_dir = self.root / "users" / _scope_key(
            self.context.workspace_id, self.context.user_id
        )
        self.workspace_dir = self.root / "workspaces" / _scope_key(
            self.context.workspace_id
        )
        self.archive_dir = self.root / "archives" / _scope_key(
            self.context.workspace_id, self.context.user_id
        )
        self.state_dir = self.root / "state" / _scope_key(
            self.context.workspace_id, self.context.user_id
        )
        for directory in (
            self.user_dir / "topics",
            self.workspace_dir / "topics",
            self.archive_dir,
            self.state_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_default_scope()

    @classmethod
    def _lock_for(cls, path: Path) -> threading.RLock:
        key = str(path.resolve())
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _migrate_legacy_default_scope(self) -> None:
        """Copy legacy root topics once; retain originals for rollback."""
        if self.context.workspace_id != "default" or self.context.user_id != "local":
            return
        marker = self.root / ".scoped-memory-migrated"
        if marker.exists():
            return
        legacy_topics = [
            path
            for path in self.root.glob("*.md")
            if path.name != INDEX_FILENAME and path.is_file()
        ]
        migrated_scopes: set[MemoryScopeKind] = set()
        for source in legacy_topics:
            try:
                frontmatter, _body = self._parse_frontmatter(
                    source.read_text(encoding="utf-8")
                )
            except OSError:
                continue
            memory_type = frontmatter.get("type", "project")
            target_scope = (
                self._scope_for_type(memory_type)
                if is_valid_memory_type(memory_type)
                else MemoryScopeKind.WORKSPACE
            )
            target = self._directory(target_scope) / "topics" / source.name
            if not target.exists():
                shutil.copy2(source, target)
                migrated_scopes.add(target_scope)
        for target_scope in migrated_scopes:
            self._regenerate_index(target_scope)
        self._atomic_write(
            marker,
            "Legacy root memory was copied into the default scoped workspace.\n",
        )

    def _directory(self, scope: MemoryScopeKind) -> Path:
        return self.user_dir if scope == MemoryScopeKind.USER else self.workspace_dir

    def _topic_path(self, filename: str, scope: MemoryScopeKind) -> Path:
        clean = os.path.basename(filename)
        if not clean.endswith(".md"):
            clean += ".md"
        if clean == INDEX_FILENAME:
            raise ValueError("MEMORY.md is generated and cannot be edited as a topic")
        return self._directory(scope) / "topics" / clean

    @staticmethod
    def _scope_for_type(memory_type: str) -> MemoryScopeKind:
        return (
            MemoryScopeKind.WORKSPACE
            if memory_type in {"project", "decision", "goal"}
            else MemoryScopeKind.USER
        )

    def load_memory_index(self, scope: MemoryScopeKind | None = None) -> str:
        scopes = [scope] if scope else [MemoryScopeKind.USER, MemoryScopeKind.WORKSPACE]
        sections: list[str] = []
        for item in scopes:
            path = self._directory(item) / INDEX_FILENAME
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
            else:
                content = "# Memory Index\n\nNo durable memories recorded."
            sections.append(f"## {item.value.title()} scope\n\n{content}")
        return "\n\n".join(sections)

    def read_memory_topic(
        self,
        filename: str,
        scope: MemoryScopeKind | None = None,
    ) -> str:
        candidates = [scope] if scope else [MemoryScopeKind.USER, MemoryScopeKind.WORKSPACE]
        for item in candidates:
            path = self._topic_path(filename, item)
            if path.exists():
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"memory topic not found: {filename}")

    def save_memory_topic(
        self,
        filename: str,
        content: str,
        memory_type: str,
        description: str,
        *,
        scope: MemoryScopeKind | None = None,
    ) -> str:
        if not is_valid_memory_type(memory_type):
            raise ValueError(f"invalid memory type: {memory_type}")
        if _SECRET_RE.search(content):
            raise ValueError("memory content appears to contain a secret")
        target_scope = scope or self._scope_for_type(memory_type)
        path = self._topic_path(filename, target_scope)
        name = path.stem
        document = (
            f"---\nname: {name}\ndescription: {description.strip()}\n"
            f"type: {memory_type}\n---\n\n{content.strip()}\n"
        )
        lock = self._lock_for(self._directory(target_scope))
        with lock:
            self._atomic_write(path, document)
            self._regenerate_index(target_scope)
        return path.name

    def delete_memory_topic(
        self,
        filename: str,
        *,
        scope: MemoryScopeKind | None = None,
    ) -> None:
        candidates = [scope] if scope else [MemoryScopeKind.USER, MemoryScopeKind.WORKSPACE]
        for item in candidates:
            path = self._topic_path(filename, item)
            if not path.exists():
                continue
            with self._lock_for(self._directory(item)):
                path.unlink()
                self._regenerate_index(item)
            return
        raise FileNotFoundError(f"memory topic not found: {filename}")

    @staticmethod
    def _parse_frontmatter(document: str) -> tuple[dict[str, str], str]:
        normalized = document.replace("\r\n", "\n")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", normalized, re.DOTALL)
        if not match:
            return {}, document.strip()
        raw_frontmatter, body = match.groups()
        frontmatter: dict[str, str] = {}
        for line in raw_frontmatter.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
        return frontmatter, body.strip()

    def scan_memory_headers(
        self,
        scope: MemoryScopeKind | None = None,
    ) -> list[dict[str, Any]]:
        scopes = [scope] if scope else [MemoryScopeKind.USER, MemoryScopeKind.WORKSPACE]
        output: list[dict[str, Any]] = []
        for item in scopes:
            for path in (self._directory(item) / "topics").glob("*.md"):
                try:
                    head = "".join(path.read_text(encoding="utf-8").splitlines(True)[:HEADER_SCAN_LINES])
                    frontmatter, preview = self._parse_frontmatter(head)
                    output.append(
                        {
                            "filename": path.name,
                            "name": frontmatter.get("name", path.stem),
                            "type": frontmatter.get("type", "unknown"),
                            "description": frontmatter.get("description", ""),
                            "preview": preview[:200],
                            "mtime": path.stat().st_mtime,
                            "scope": item.value,
                        }
                    )
                except OSError:
                    continue
        return sorted(output, key=lambda entry: entry["mtime"], reverse=True)

    def check_stale_memories(self, days: int = STALE_WARN_DAYS) -> list[dict[str, Any]]:
        import time

        now = time.time()
        return [
            {**item, "age_days": int((now - item["mtime"]) / 86400)}
            for item in self.scan_memory_headers()
            if now - item["mtime"] > days * 86400
        ]

    def _regenerate_index(self, scope: MemoryScopeKind) -> None:
        lines = ["# Memory Index", ""]
        for item in self.scan_memory_headers(scope):
            label = get_type_display_name(item["type"])
            lines.append(f"- **[{label}]** `{item['filename']}` — {item['description']}")
        if len(lines) == 2:
            lines.append("No durable memories recorded.")
        content = "\n".join(lines[:MAX_INDEX_LINES]) + "\n"
        if len(content.encode("utf-8")) > MAX_INDEX_BYTES:
            content = content.encode("utf-8")[:MAX_INDEX_BYTES].decode(
                "utf-8", errors="ignore"
            ) + "\n\n> Index truncated.\n"
        self._atomic_write(self._directory(scope) / INDEX_FILENAME, content)

    @property
    def archive_file(self) -> Path:
        return self.archive_dir / "history.jsonl"

    @property
    def curator_state_file(self) -> Path:
        return self.state_dir / "curator.json"

    def append_archive(
        self,
        *,
        source_id: str,
        summary: str,
        source_message_ids: Iterable[str] = (),
    ) -> MemoryArchiveRecord:
        clean_summary = summary.strip()
        if not clean_summary:
            raise ValueError("archive summary cannot be empty")
        with self._lock_for(self.archive_file):
            existing = self.read_archives()
            duplicate = next((row for row in existing if row.source_id == source_id), None)
            if duplicate:
                return duplicate
            record = MemoryArchiveRecord(
                cursor=max((row.cursor for row in existing), default=0) + 1,
                source_id=source_id,
                workspace_id=self.context.workspace_id,
                user_id=self.context.user_id,
                session_id=self.context.session_id,
                agent_id=self.context.agent_id,
                summary=clean_summary,
                source_message_ids=tuple(source_message_ids),
            )
            with self.archive_file.open("a", encoding="utf-8", newline="\n") as file:
                file.write(record.model_dump_json() + "\n")
                file.flush()
                os.fsync(file.fileno())
            return record

    def read_archives(
        self,
        *,
        since_cursor: int = 0,
        session_id: str | None = None,
    ) -> list[MemoryArchiveRecord]:
        if not self.archive_file.exists():
            return []
        records: list[MemoryArchiveRecord] = []
        for line in self.archive_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = MemoryArchiveRecord.model_validate_json(line)
            except Exception:
                continue
            if record.cursor <= since_cursor:
                continue
            if session_id is not None and record.session_id != session_id:
                continue
            records.append(record)
        return records

    def get_curator_cursor(self) -> int:
        if not self.curator_state_file.exists():
            return 0
        try:
            data = json.loads(self.curator_state_file.read_text(encoding="utf-8"))
            return max(0, int(data.get("cursor", 0)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def set_curator_cursor(self, cursor: int) -> None:
        self._atomic_write(
            self.curator_state_file,
            json.dumps({"cursor": max(0, cursor)}, ensure_ascii=False, indent=2) + "\n",
        )

    def build_injection_text(
        self,
        *,
        max_tokens: int,
        max_topics: int,
        recent_archive_tokens: int,
    ) -> str:
        parts = [self.load_memory_index()]
        topic_budget = max(0, max_tokens - recent_archive_tokens)
        for header in self.scan_memory_headers()[:max_topics]:
            scope = MemoryScopeKind(header["scope"])
            try:
                document = self.read_memory_topic(header["filename"], scope)
            except OSError:
                continue
            candidate = f"### {scope.value}/{header['filename']}\n{document}"
            if rough_token_count_estimation("\n\n".join([*parts, candidate])) > topic_budget:
                break
            parts.append(candidate)

        recent = self.read_archives(
            since_cursor=self.get_curator_cursor(),
            session_id=self.context.session_id,
        )
        if recent and recent_archive_tokens:
            text = "\n".join(
                f"- [{row.cursor}] {row.summary}" for row in recent[-20:]
            )
            parts.append(
                "## Current session archived context\n"
                + _truncate_to_tokens(text, recent_archive_tokens)
            )
        return _truncate_to_tokens("\n\n".join(parts), max_tokens)

    def apply_curator_operation(self, operation: MemoryCuratorOperation) -> None:
        if operation.operation == "ignore":
            return
        if operation.operation == "delete":
            self.delete_memory_topic(operation.filename, scope=operation.scope)
            return
        self.save_memory_topic(
            operation.filename,
            operation.content,
            operation.memory_type,
            operation.description,
            scope=operation.scope,
        )
