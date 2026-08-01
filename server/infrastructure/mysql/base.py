"""SQLAlchemy metadata shared by MySQL ORM models and Alembic."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampedModel:
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), onupdate=func.utc_timestamp(6), nullable=False)
