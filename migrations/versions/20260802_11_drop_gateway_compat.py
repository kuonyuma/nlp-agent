"""drop retired Gateway compatibility projection

Revision ID: 20260802_11
Revises: 20260802_10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_11"
down_revision = "20260802_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("nlp_gateway_compat")


def downgrade() -> None:
    op.create_table(
        "nlp_gateway_compat",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint("uq_nlp_gateway_compat_namespace_aggregate", "nlp_gateway_compat", ["namespace", "aggregate_id"])
