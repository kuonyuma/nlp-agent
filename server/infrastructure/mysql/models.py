"""Minimal identity and session tables required by the MySQL foundation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedModel


UUID = String(36, collation="ascii_bin")


class UserModel(TimestampedModel, Base):
    __tablename__ = "nlp_users"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    sessions: Mapped[list["SessionModel"]] = relationship(back_populates="user")


class WorkspaceModel(TimestampedModel, Base):
    __tablename__ = "nlp_workspaces"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")


class SessionModel(TimestampedModel, Base):
    __tablename__ = "nlp_sessions"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_nlp_sessions_token_hash"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="sessions")
