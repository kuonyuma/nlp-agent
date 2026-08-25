"""Opt-in persistent project storage with traversal and symlink defenses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from configs.settings import settings


class ProjectStorage(Protocol):
    def put(self, project_id: str, relative_path: str, content: bytes) -> None: ...
    def get(self, project_id: str, relative_path: str) -> bytes: ...


class DisabledProjectStorage:
    def put(self, project_id: str, relative_path: str, content: bytes) -> None:
        del project_id, relative_path, content
        raise PermissionError("persistent Sandbox Project Storage is not enabled")

    def get(self, project_id: str, relative_path: str) -> bytes:
        del project_id, relative_path
        raise PermissionError("persistent Sandbox Project Storage is not enabled")


class LocalProjectStorage:
    def __init__(self, root: Path, *, enabled: bool = False) -> None:
        self.root = root.resolve()
        self.enabled = enabled
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str, relative_path: str) -> Path:
        if not self.enabled:
            raise PermissionError("persistent Sandbox Project Storage is not enabled")
        if not project_id or not relative_path or Path(relative_path).is_absolute():
            raise ValueError("project path must be relative and non-empty")
        raw_path = self.root / project_id / relative_path
        current = self.root
        try:
            relative_parts = raw_path.relative_to(self.root).parts
        except ValueError as error:
            raise ValueError("project path escapes the storage root") from error
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("symlinked project paths are not allowed")
        project = (self.root / project_id).resolve()
        path = raw_path.resolve()
        if self.root not in path.parents or project not in path.parents:
            raise ValueError("project path escapes the storage root")
        if project.is_symlink() or path.is_symlink():
            raise ValueError("symlinked project paths are not allowed")
        return path

    def put(self, project_id: str, relative_path: str, content: bytes) -> None:
        path = self._path(project_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_symlink():
            raise ValueError("symlinked project paths are not allowed")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def get(self, project_id: str, relative_path: str) -> bytes:
        path = self._path(project_id, relative_path)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(relative_path)
        return path.read_bytes()


def create_project_storage(*, enabled: bool, root: Path | None) -> ProjectStorage:
    """Return the explicit opt-in backend; persistence is never implicit."""
    if not enabled or root is None:
        return DisabledProjectStorage()
    return LocalProjectStorage(root, enabled=True)


def configured_project_storage() -> ProjectStorage:
    configured_root = settings.NLP_AGENT_SANDBOX_PROJECT_STORAGE_ROOT.strip()
    return create_project_storage(
        enabled=settings.NLP_AGENT_SANDBOX_PROJECT_STORAGE_ENABLED,
        root=Path(configured_root) if configured_root else None,
    )
