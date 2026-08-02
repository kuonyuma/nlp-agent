"""add normalized guided-session and user-preference state

Revision ID: 20260802_10
Revises: 20260801_09
"""
from alembic import op

from server.infrastructure.mysql.models import GuidedSessionModel, UserPreferenceModel

revision = "20260802_10"
down_revision = "20260801_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    GuidedSessionModel.__table__.create(bind=bind)
    UserPreferenceModel.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    UserPreferenceModel.__table__.drop(bind=bind)
    GuidedSessionModel.__table__.drop(bind=bind)
