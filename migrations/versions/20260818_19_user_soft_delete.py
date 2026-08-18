"""user soft-delete lifecycle (阶段5 / P1-2).

Adds ``deleted_at`` to ``nlp_users`` and indexes it so active-user queries
remain efficient. Soft delete preserves learning history, classroom records,
and audit trails while preventing the deleted account from being returned by
normal queries or used for authentication.

Revision ID: 20260818_19
Revises: 20260818_18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


revision = "20260818_19"
down_revision = "20260818_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nlp_users",
        sa.Column(
            "deleted_at",
            DATETIME(fsp=6),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_nlp_users_deleted_at",
        "nlp_users",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_nlp_users_deleted_at", table_name="nlp_users")
    op.drop_column("nlp_users", "deleted_at")
