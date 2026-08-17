"""merge migration heads

Revision ID: 1f34d106eba5
Revises: 20260814_16, 20260815_17
Create Date: 2026-08-17 17:10:07.076725
"""
from alembic import op
import sqlalchemy as sa


revision = '1f34d106eba5'
down_revision = ('20260814_16', '20260815_17')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
