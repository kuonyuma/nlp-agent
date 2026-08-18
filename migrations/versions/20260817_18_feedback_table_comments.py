"""apply comments to the feedback tables

Revision ID: 20260817_18
Revises: 1f34d106eba5
Create Date: 2026-08-17 17:30:00
"""

from alembic import op


revision = "20260817_18"
down_revision = "1f34d106eba5"
branch_labels = None
depends_on = None


FEEDBACK_TABLE_COMMENTS = {
    "nlp_feedback_threads": "学生意见反馈会话，按用户聚合反馈线程。",
    "nlp_feedback_messages": "反馈会话中的逐条消息与发送方类型。",
}


def _mysql_string_literal(value: str) -> str:
    """Return a safely quoted literal for the static migration comments."""

    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    for table_name, table_comment in FEEDBACK_TABLE_COMMENTS.items():
        op.execute(
            f"ALTER TABLE `{table_name}` COMMENT = "
            f"{_mysql_string_literal(table_comment)}"
        )


def downgrade() -> None:
    for table_name in FEEDBACK_TABLE_COMMENTS:
        op.execute(f"ALTER TABLE `{table_name}` COMMENT = ''")
