"""add LLM-generated session title basis timestamp

Revision ID: 20260820_25
Revises: 20260820_24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


revision = "20260820_25"
down_revision = "20260820_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``title`` already exists and holds the raw first-message text until the
    # LLM summarizer overwrites it.  ``title_updated_at`` records the *basis*
    # of the last summary (the newest completed turn's ``completed_at``), so a
    # conditional UPDATE can reject out-of-order writes without a second column.
    op.add_column(
        "nlp_conversations",
        sa.Column("title_updated_at", DATETIME(fsp=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nlp_conversations", "title_updated_at")
