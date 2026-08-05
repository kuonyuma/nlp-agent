"""add classroom and RBAC menu projections

Revision ID: 20260804_14
Revises: 20260804_13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_14"
down_revision = "20260804_13"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
    ]


def upgrade() -> None:
    op.create_table(
        "nlp_classrooms",
        sa.Column("id", sa.String(36, collation="ascii_bin"), primary_key=True),
        sa.Column("workspace_id", sa.String(36, collation="ascii_bin"), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["nlp_workspaces.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "nlp_classroom_members",
        sa.Column("classroom_id", sa.String(36, collation="ascii_bin"), nullable=False),
        sa.Column("user_id", sa.String(36, collation="ascii_bin"), nullable=False),
        sa.Column("member_role", sa.String(16), nullable=False, server_default="student"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("classroom_id", "user_id"),
        sa.ForeignKeyConstraint(["classroom_id"], ["nlp_classrooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["nlp_users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "nlp_menus",
        sa.Column("id", sa.String(36, collation="ascii_bin"), primary_key=True),
        sa.Column("parent_id", sa.String(36, collation="ascii_bin")),
        sa.Column("menu_type", sa.String(16), nullable=False), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("route_path", sa.String(255)), sa.Column("component_key", sa.String(128)),
        sa.Column("permission_id", sa.String(36, collation="ascii_bin")), sa.Column("client_scope", sa.String(16)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"), *_timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["nlp_menus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["nlp_permissions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("parent_id", "name", name="uq_nlp_menus_parent_name"),
    )
    op.create_table(
        "nlp_role_menus", sa.Column("role_id", sa.String(36, collation="ascii_bin"), nullable=False),
        sa.Column("menu_id", sa.String(36, collation="ascii_bin"), nullable=False), sa.PrimaryKeyConstraint("role_id", "menu_id"),
        sa.ForeignKeyConstraint(["role_id"], ["nlp_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_id"], ["nlp_menus.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("nlp_role_menus")
    op.drop_table("nlp_menus")
    op.drop_table("nlp_classroom_members")
    op.drop_table("nlp_classrooms")
