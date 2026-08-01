"""create MySQL authority tables for Redis/Worker reliability

Revision ID: 20260801_03
Revises: 20260801_02
"""

from alembic import op

from server.infrastructure.mysql.models import DeadLetterModel, OutboxMessageModel, ToolCallModel, TurnCancellationModel

revision = "20260801_03"
down_revision = "20260801_02"
branch_labels = None
depends_on = None

TABLES = (OutboxMessageModel.__table__, TurnCancellationModel.__table__, ToolCallModel.__table__, DeadLetterModel.__table__)


def upgrade() -> None:
    for table in TABLES:
        table.create(bind=op.get_bind())


def downgrade() -> None:
    for table in reversed(TABLES):
        table.drop(bind=op.get_bind())
