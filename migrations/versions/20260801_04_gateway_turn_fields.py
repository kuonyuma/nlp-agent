"""add Gateway-compatible Turn lifecycle fields

Revision ID: 20260801_04
Revises: 20260801_03
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260801_04"
down_revision = "20260801_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        return
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("nlp_turns")}
    additions = (
        ("error_kind", sa.String(128)), ("error_message", sa.String(1000)),
        ("started_at", mysql.DATETIME(fsp=6)), ("completed_at", mysql.DATETIME(fsp=6)),
    )
    for name, column_type in additions:
        if name not in existing:
            op.add_column("nlp_turns", sa.Column(name, column_type))


def downgrade() -> None:
    # Revision 02 dynamically builds this table from the current Model; no
    # downgrade DDL is safe without a frozen historical table definition.
    return
