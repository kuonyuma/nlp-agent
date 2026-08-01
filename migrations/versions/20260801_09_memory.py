"""add MySQL memory and archive storage

Revision ID: 20260801_09
Revises: 20260801_08
"""
from alembic import op
from server.infrastructure.mysql.models import MemoryArchiveModel, MemoryCursorModel

revision = "20260801_09"
down_revision = "20260801_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    MemoryArchiveModel.__table__.create(bind=bind)
    MemoryCursorModel.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    MemoryCursorModel.__table__.drop(bind=bind)
    MemoryArchiveModel.__table__.drop(bind=bind)
