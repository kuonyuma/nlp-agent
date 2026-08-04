"""add RBAC authorization audit log

Revision ID: 20260804_13
Revises: 20260804_12
Create Date: 2026-08-04 00:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_13"
down_revision = "20260804_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nlp_authorization_audit_logs",
        sa.Column("id", sa.String(length=36, collation="ascii_bin"), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36, collation="ascii_bin")),
        sa.Column("target_user_id", sa.String(length=36, collation="ascii_bin")),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("permission_code", sa.String(length=128)),
        sa.Column("resource_type", sa.String(length=64)),
        sa.Column("resource_id", sa.String(length=128)),
        sa.Column("detail_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["nlp_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["nlp_users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_nlp_authorization_audit_actor_created", "nlp_authorization_audit_logs", ["actor_user_id", "created_at"])
    op.create_index("ix_nlp_authorization_audit_target_created", "nlp_authorization_audit_logs", ["target_user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("nlp_authorization_audit_logs")
