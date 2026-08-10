"""Turn-local model profile selection shared by Agent runtime components."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_current_model_profile: ContextVar[str | None] = ContextVar(
    "current_model_profile", default=None
)


def current_model_profile() -> str | None:
    return _current_model_profile.get()


@contextmanager
def bind_model_profile(profile: str | None) -> Iterator[None]:
    token = _current_model_profile.set(profile)
    try:
        yield
    finally:
        _current_model_profile.reset(token)
