"""expand conversation identifiers for runtime session IDs

Revision ID: 20260805_15
Revises: 20260804_14
Create Date: 2026-08-05 00:00:00
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260805_15"
down_revision = "20260804_14"
branch_labels = None
depends_on = None


CONVERSATION_FOREIGN_KEYS = {
    "nlp_conversation_messages": "fk_nlp_conversation_messages_conversation_id_nlp_conversations",
    "nlp_exercise_sessions": "fk_nlp_exercise_sessions_conversation_id_nlp_conversations",
    "nlp_guided_sessions": "fk_nlp_guided_sessions_conversation_id_nlp_conversations",
    "nlp_turns": "fk_nlp_turns_conversation_id_nlp_conversations",
}


def _identifier_type(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _drop_foreign_keys() -> None:
    for table_name, constraint_name in CONVERSATION_FOREIGN_KEYS.items():
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")


def _create_foreign_keys() -> None:
    for table_name, constraint_name in CONVERSATION_FOREIGN_KEYS.items():
        op.create_foreign_key(
            constraint_name,
            table_name,
            "nlp_conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )


def _resize_identifiers(*, old_length: int, new_length: int) -> None:
    _drop_foreign_keys()
    op.alter_column(
        "nlp_conversations",
        "id",
        existing_type=_identifier_type(old_length),
        type_=_identifier_type(new_length),
        existing_nullable=False,
    )
    for table_name in CONVERSATION_FOREIGN_KEYS:
        op.alter_column(
            table_name,
            "conversation_id",
            existing_type=_identifier_type(old_length),
            type_=_identifier_type(new_length),
            existing_nullable=False,
        )
    _create_foreign_keys()


def upgrade() -> None:
    _resize_identifiers(old_length=36, new_length=128)


def downgrade() -> None:
    if not context.is_offline_mode():
        oversized = op.get_bind().execute(
            sa.text(
                "SELECT COUNT(*) FROM nlp_conversations "
                "WHERE CHAR_LENGTH(id) > 36"
            )
        ).scalar_one()
        if int(oversized):
            raise RuntimeError(
                "cannot shrink conversation identifiers while IDs exceed 36 characters"
            )
    _resize_identifiers(old_length=128, new_length=36)
