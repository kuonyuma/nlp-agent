"""create second-wave durable state tables

Revision ID: 20260801_06
Revises: 20260801_05
"""
from alembic import op
from server.infrastructure.mysql.models import AgentCheckpointModel, ConversationTranscriptModel, MemoryDocumentModel, RuntimeConfigVersionModel, ToolAuditModel

revision = "20260801_06"
down_revision = "20260801_05"
branch_labels = None
depends_on = None
TABLES = (AgentCheckpointModel.__table__, ConversationTranscriptModel.__table__, MemoryDocumentModel.__table__, ToolAuditModel.__table__, RuntimeConfigVersionModel.__table__)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind)
