"""add release notes table and manage permission

Revision ID: 20260813_16
Revises: 20260805_15
Create Date: 2026-08-13 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from core.rbac import Permission
from server.rbac.catalog import permission_id, permission_row, permission_scope, role_id


revision = "20260813_16"
down_revision = "20260805_15"
branch_labels = None
depends_on = None


RELEASE_NOTES_PERMISSION = Permission.SYSTEM_RELEASE_NOTES_MANAGE


def upgrade() -> None:
    op.create_table(
        "nlp_release_notes",
        sa.Column("id", sa.String(length=36, collation="ascii_bin"), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("released_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("notes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="published", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_nlp_release_notes_version"),
        sa.Index("ix_nlp_release_notes_status_released_at", "status", "released_at"),
    )

    permissions_table = sa.table(
        "nlp_permissions",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("domain_name", sa.String()),
        sa.column("resource_name", sa.String()),
        sa.column("action_name", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_builtin", sa.Boolean()),
    )
    role_permissions_table = sa.table(
        "nlp_role_permissions",
        sa.column("role_id", sa.String()),
        sa.column("permission_id", sa.String()),
    )
    role_permission_scopes_table = sa.table(
        "nlp_role_permission_scopes",
        sa.column("role_id", sa.String()),
        sa.column("permission_id", sa.String()),
        sa.column("scope_type", sa.String()),
    )

    op.bulk_insert(permissions_table, [permission_row(RELEASE_NOTES_PERMISSION)])
    developer_role_id = role_id("developer")
    manage_permission_id = permission_id(RELEASE_NOTES_PERMISSION)
    op.bulk_insert(
        role_permissions_table,
        [{"role_id": developer_role_id, "permission_id": manage_permission_id}],
    )
    op.bulk_insert(
        role_permission_scopes_table,
        [{
            "role_id": developer_role_id,
            "permission_id": manage_permission_id,
            "scope_type": permission_scope(RELEASE_NOTES_PERMISSION),
        }],
    )


def downgrade() -> None:
    manage_permission_id = permission_id(RELEASE_NOTES_PERMISSION)
    developer_role_id = role_id("developer")
    op.execute(
        sa.text(
            "DELETE FROM nlp_role_permission_scopes "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ).bindparams(role_id=developer_role_id, permission_id=manage_permission_id)
    )
    op.execute(
        sa.text(
            "DELETE FROM nlp_role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ).bindparams(role_id=developer_role_id, permission_id=manage_permission_id)
    )
    op.execute(
        sa.text("DELETE FROM nlp_permissions WHERE id = :permission_id").bindparams(
            permission_id=manage_permission_id
        )
    )
    op.drop_table("nlp_release_notes")
