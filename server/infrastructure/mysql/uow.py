"""One explicit transaction per application command or worker operation."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class AsyncUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> "AsyncUnitOfWork":
        self.session = self._session_factory()
        await self.session.begin()
        return self

    async def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work has not been entered")
        await self.session.commit()

    async def rollback(self) -> None:
        if self.session is not None:
            await self.session.rollback()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self.session is None:
            return
        try:
            if exc_type is not None:
                await self.session.rollback()
            elif self.session.in_transaction():
                await self.session.rollback()
        finally:
            await self.session.close()


class UnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def begin(self) -> AsyncUnitOfWork:
        return AsyncUnitOfWork(self._session_factory)
