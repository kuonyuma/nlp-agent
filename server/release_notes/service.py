"""Release note application service for the developer control plane and student UI.

Each row is one published or draft release version.  The version number itself
is injected into the web UI at build time from ``package.json``; this table is
the single source of truth for the accompanying changelog copy.
"""

from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.infrastructure.mysql.models import ReleaseNoteModel

VALID_STATUSES = ("draft", "published")


class ReleaseNoteConflictError(ValueError):
    """A release note already exists for the requested version."""


class ReleaseNoteNotFoundError(ValueError):
    """No release note exists for the requested id."""


class ReleaseNoteCrud:
    """Narrow persistence primitives so the service logic stays testable."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, *, statuses: tuple[str, ...]) -> list[ReleaseNoteModel]:
        statement = select(ReleaseNoteModel)
        if statuses:
            statement = statement.where(ReleaseNoteModel.status.in_(statuses))
        statement = statement.order_by(
            ReleaseNoteModel.released_at.desc(),
            ReleaseNoteModel.version.desc(),
        )
        return list(await self._session.scalars(statement))

    async def by_version(self, version: str) -> ReleaseNoteModel | None:
        return await self._session.scalar(
            select(ReleaseNoteModel).where(ReleaseNoteModel.version == version)
        )

    async def get(self, note_id: str) -> ReleaseNoteModel | None:
        return await self._session.scalar(
            select(ReleaseNoteModel).where(ReleaseNoteModel.id == note_id)
        )

    async def add(self, note: ReleaseNoteModel) -> None:
        self._session.add(note)

    async def delete(self, note: ReleaseNoteModel) -> None:
        await self._session.delete(note)


class ReleaseNoteService:
    def __init__(
        self,
        crud_factory: Callable[[AsyncSession], ReleaseNoteCrud],
    ) -> None:
        self._crud_factory = crud_factory

    async def list(
        self, session: AsyncSession, *, include_drafts: bool = False
    ) -> list[ReleaseNoteModel]:
        statuses: tuple[str, ...] = (
            ("draft", "published") if include_drafts else ("published",)
        )
        return await self._crud_factory(session).list(statuses=statuses)

    async def create(
        self,
        session: AsyncSession,
        *,
        version: str,
        released_at: object,
        notes: list[str],
        status: str,
    ) -> ReleaseNoteModel:
        self._validate(version=version, notes=notes, status=status)
        crud = self._crud_factory(session)
        if await crud.by_version(version) is not None:
            raise ReleaseNoteConflictError(f"version {version!r} already exists")
        note = ReleaseNoteModel(
            id=str(uuid.uuid4()),
            version=version,
            released_at=released_at,
            notes_json=list(notes),
            status=status,
        )
        await crud.add(note)
        return note

    async def update(
        self,
        session: AsyncSession,
        *,
        note_id: str,
        version: str,
        released_at: object,
        notes: list[str],
        status: str,
    ) -> ReleaseNoteModel:
        self._validate(version=version, notes=notes, status=status)
        crud = self._crud_factory(session)
        note = await crud.get(note_id)
        if note is None:
            raise ReleaseNoteNotFoundError(note_id)
        existing = await crud.by_version(version)
        if existing is not None and existing.id != note_id:
            raise ReleaseNoteConflictError(f"version {version!r} already exists")
        note.version = version
        note.released_at = released_at
        note.notes_json = list(notes)
        note.status = status
        return note

    async def delete(self, session: AsyncSession, *, note_id: str) -> None:
        crud = self._crud_factory(session)
        note = await crud.get(note_id)
        if note is None:
            raise ReleaseNoteNotFoundError(note_id)
        await crud.delete(note)

    @staticmethod
    def _validate(*, version: str, notes: list[str], status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid release note status {status!r}")
        if len(version) > 32:
            raise ValueError("version is too long")
        if not notes:
            raise ValueError("release note items cannot be empty")
        if any(not item.strip() for item in notes):
            raise ValueError("release note items cannot be blank")


release_note_service = ReleaseNoteService(ReleaseNoteCrud)
