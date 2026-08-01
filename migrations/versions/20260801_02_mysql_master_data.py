"""create teaching, learning, conversation, turn and event master data

Revision ID: 20260801_02
Revises: 20260801_01
Create Date: 2026-08-01 00:00:00
"""

from alembic import op

from server.infrastructure.mysql.models import (
    BlueprintRubricModel, ConversationMessageModel, ConversationModel, CourseCatalogModel,
    CourseCatalogVersionModel, CourseTopicModel, ExerciseAttemptModel, ExerciseQuestionModel,
    ExerciseSessionModel, KnowledgePointModel, LearningEvidenceModel, TeachingBlueprintModel,
    TeachingGoalModel, TurnEventModel, TurnModel,
)


revision = "20260801_02"
down_revision = "20260801_01"
branch_labels = None
depends_on = None

TABLES = (
    TeachingGoalModel.__table__, CourseCatalogModel.__table__, CourseTopicModel.__table__,
    KnowledgePointModel.__table__, TeachingBlueprintModel.__table__, BlueprintRubricModel.__table__,
    CourseCatalogVersionModel.__table__, ConversationModel.__table__, TurnModel.__table__,
    ConversationMessageModel.__table__, TurnEventModel.__table__, ExerciseSessionModel.__table__,
    ExerciseQuestionModel.__table__, ExerciseAttemptModel.__table__, LearningEvidenceModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind)
