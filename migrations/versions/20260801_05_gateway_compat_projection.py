"""add transitional Gateway aggregate projection

Revision ID: 20260801_05
Revises: 20260801_04
"""
from alembic import op
from server.infrastructure.mysql.models import GatewayCompatModel

revision = "20260801_05"
down_revision = "20260801_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    GatewayCompatModel.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    GatewayCompatModel.__table__.drop(bind=op.get_bind())
