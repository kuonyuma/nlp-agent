"""add per-user feedback threads

Revision ID: 20260814_16
Revises: 20260805_15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


revision = "20260814_16"
down_revision = "20260805_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = sa.String(36, collation="ascii_bin")
    timestamp_type = DATETIME(fsp=6)
    op.create_table(
        "nlp_feedback_threads",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("developer_read_at", timestamp_type, nullable=True),
        sa.Column("created_at", timestamp_type, server_default=sa.func.utc_timestamp(6), nullable=False),
        sa.Column("updated_at", timestamp_type, server_default=sa.func.utc_timestamp(6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["nlp_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_nlp_feedback_threads_user_id"),
    )
    op.create_table(
        "nlp_feedback_messages",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("thread_id", uuid_type, nullable=False),
        sa.Column("sender_user_id", uuid_type, nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", timestamp_type, server_default=sa.func.utc_timestamp(6), nullable=False),
        sa.Column("updated_at", timestamp_type, server_default=sa.func.utc_timestamp(6), nullable=False),
        sa.ForeignKeyConstraint(["sender_user_id"], ["nlp_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["nlp_feedback_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("nlp_feedback_messages")
    op.drop_table("nlp_feedback_threads")
