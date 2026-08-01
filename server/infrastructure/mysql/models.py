"""Minimal identity and session tables required by the MySQL foundation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedModel


UUID = String(36, collation="ascii_bin")


class UserModel(TimestampedModel, Base):
    __tablename__ = "nlp_users"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    sessions: Mapped[list["SessionModel"]] = relationship(back_populates="user")


class WorkspaceModel(TimestampedModel, Base):
    __tablename__ = "nlp_workspaces"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")


class SessionModel(TimestampedModel, Base):
    __tablename__ = "nlp_sessions"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_nlp_sessions_token_hash"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="sessions")


class TeachingGoalModel(TimestampedModel, Base):
    __tablename__ = "nlp_teaching_goals"

    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_workspaces.id", ondelete="RESTRICT"), primary_key=True)
    goal_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, server_default="0")


class CourseCatalogModel(TimestampedModel, Base):
    __tablename__ = "nlp_course_catalogs"

    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_workspaces.id", ondelete="RESTRICT"), primary_key=True)
    revision: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, server_default="0")
    published_revision: Mapped[int | None] = mapped_column(BIGINT(unsigned=True))


class CourseTopicModel(TimestampedModel, Base):
    __tablename__ = "nlp_course_topics"
    __table_args__ = (UniqueConstraint("workspace_id", "id", name="uq_nlp_course_topics_workspace_id_id"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_course_catalogs.workspace_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class KnowledgePointModel(TimestampedModel, Base):
    __tablename__ = "nlp_knowledge_points"
    __table_args__ = (UniqueConstraint("workspace_id", "id", name="uq_nlp_knowledge_points_workspace_id_id"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_course_catalogs.workspace_id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_course_topics.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class TeachingBlueprintModel(TimestampedModel, Base):
    __tablename__ = "nlp_teaching_blueprints"
    __table_args__ = (Index("ix_nlp_blueprints_assignment", "workspace_id", "kind", "topic_id", "knowledge_point_id", "status"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_course_catalogs.workspace_id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_id: Mapped[str] = mapped_column(UUID, nullable=False)
    knowledge_point_id: Mapped[str | None] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, server_default="0")


class BlueprintRubricModel(Base):
    __tablename__ = "nlp_blueprint_rubrics"
    __table_args__ = (UniqueConstraint("blueprint_id", "sort_order", name="uq_nlp_blueprint_rubrics_blueprint_id_sort_order"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_teaching_blueprints.id", ondelete="CASCADE"), nullable=False)
    criterion: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class CourseCatalogVersionModel(Base):
    __tablename__ = "nlp_course_catalog_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "revision", name="uq_nlp_course_catalog_versions_workspace_id_revision"),)

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_course_catalogs.workspace_id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)


class ConversationModel(TimestampedModel, Base):
    __tablename__ = "nlp_conversations"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    last_message_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class TurnModel(TimestampedModel, Base):
    __tablename__ = "nlp_turns"
    __table_args__ = (UniqueConstraint("user_id", "conversation_id", "idempotency_key", name="uq_nlp_turns_user_conversation_idempotency"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="accepted")
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_text: Mapped[str | None] = mapped_column(Text)
    learning_state_json: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    claim_generation: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, server_default="0")
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class ConversationMessageModel(Base):
    __tablename__ = "nlp_conversation_messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence", name="uq_nlp_conversation_messages_conversation_id_sequence"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_conversations.id", ondelete="CASCADE"), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("nlp_turns.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)


class TurnEventModel(Base):
    __tablename__ = "nlp_turn_events"
    __table_args__ = (UniqueConstraint("turn_id", "sequence", name="uq_nlp_turn_events_turn_id_sequence"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    turn_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_turns.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    claim_generation: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, server_default="0")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)


class ExerciseSessionModel(TimestampedModel, Base):
    __tablename__ = "nlp_exercise_sessions"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID, nullable=False)
    user_id: Mapped[str] = mapped_column(UUID, nullable=False)
    topic_id: Mapped[str] = mapped_column(UUID, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    blueprint_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class ExerciseQuestionModel(Base):
    __tablename__ = "nlp_exercise_questions"
    __table_args__ = (UniqueConstraint("exercise_session_id", "sequence", name="uq_nlp_exercise_questions_session_sequence"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    exercise_session_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_exercise_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_json: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)


class ExerciseAttemptModel(Base):
    __tablename__ = "nlp_exercise_attempts"
    __table_args__ = (UniqueConstraint("exercise_question_id", "attempt_number", name="uq_nlp_exercise_attempts_question_attempt"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    exercise_question_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_exercise_questions.id", ondelete="CASCADE"), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_matches_json: Mapped[list] = mapped_column(JSON, nullable=False)
    normalized_score: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)


class LearningEvidenceModel(Base):
    __tablename__ = "nlp_learning_evidence"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    exercise_session_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_exercise_sessions.id", ondelete="CASCADE"), nullable=False)
    exercise_question_id: Mapped[str] = mapped_column(UUID, ForeignKey("nlp_exercise_questions.id", ondelete="CASCADE"), nullable=False)
    blueprint_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    learner_answer: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_score: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=func.utc_timestamp(6), nullable=False)
