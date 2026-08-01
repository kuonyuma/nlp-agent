"""add LangGraph MySQL checkpoint tables

Revision ID: 20260801_07
Revises: 20260801_06
"""
from alembic import op

from server.infrastructure.mysql.models import (
    LangGraphCheckpointBlobModel,
    LangGraphCheckpointModel,
    LangGraphCheckpointWriteModel,
)

revision = "20260801_07"
down_revision = "20260801_06"
branch_labels = None
depends_on = None
TABLES = (
    LangGraphCheckpointModel.__table__,
    LangGraphCheckpointBlobModel.__table__,
    LangGraphCheckpointWriteModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind)
