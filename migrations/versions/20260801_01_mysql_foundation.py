"""create mysql persistence foundation

Revision ID: 20260801_01
Revises:
Create Date: 2026-08-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260801_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nlp_users",
        sa.Column("id", sa.String(length=36, collation="ascii_bin"), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
    )
    op.create_table(
        "nlp_workspaces",
        sa.Column("id", sa.String(length=36, collation="ascii_bin"), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
    )
    op.create_table(
        "nlp_sessions",
        sa.Column("id", sa.String(length=36, collation="ascii_bin"), primary_key=True),
        sa.Column("user_id", sa.String(length=36, collation="ascii_bin"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36, collation="ascii_bin"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("csrf_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.ForeignKeyConstraint(["user_id"], ["nlp_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["nlp_workspaces.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("token_hash", name="uq_nlp_sessions_token_hash"),
    )
    op.create_index("ix_nlp_sessions_user_id", "nlp_sessions", ["user_id"])
    op.create_index("ix_nlp_sessions_workspace_id", "nlp_sessions", ["workspace_id"])
    op.create_index("ix_nlp_sessions_expires_at", "nlp_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("nlp_sessions")
    op.drop_table("nlp_workspaces")
    op.drop_table("nlp_users")
