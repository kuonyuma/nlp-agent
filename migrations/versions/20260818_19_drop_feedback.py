"""drop feedback tables (revert of PR #56)

Revision ID: 20260818_19
Revises: 20260817_18
Create Date: 2026-08-18
"""

from alembic import op

revision = "20260818_19"
down_revision = "20260817_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("nlp_feedback_messages")
    op.drop_table("nlp_feedback_threads")


def downgrade() -> None:
    # Recreating the feedback tables is intentionally out of scope: this
    # migration exists only to unwind the PR #56 schema on databases that
    # already applied it. Re-introducing feedback should go through a new
    # migration, not by downgrading this one.
    pass
