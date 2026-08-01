"""add MySQL observability envelope storage

Revision ID: 20260801_08
Revises: 20260801_07
"""
from alembic import op
from server.infrastructure.mysql.models import ObservabilityRecordModel

revision = "20260801_08"
down_revision = "20260801_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ObservabilityRecordModel.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    ObservabilityRecordModel.__table__.drop(bind=op.get_bind())
