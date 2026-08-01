"""Narrow SQLAlchemy CRUD primitives; concurrency policy belongs to services."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.infrastructure.mysql.models import (
    ConversationModel, CourseCatalogModel, CourseCatalogVersionModel, CourseTopicModel,
    ExerciseSessionModel, KnowledgePointModel, TeachingBlueprintModel, TurnEventModel, TurnModel,
)


class TeachingCrud:
    async def lock_catalog(self, session: AsyncSession, workspace_id: str) -> CourseCatalogModel | None:
        return await session.scalar(select(CourseCatalogModel).where(CourseCatalogModel.workspace_id == workspace_id).with_for_update())

    async def replace_catalog(self, session: AsyncSession, catalog: CourseCatalogModel, *, topics: list[dict], blueprints: list[dict], summary: str) -> None:
        await session.execute(CourseTopicModel.__table__.delete().where(CourseTopicModel.workspace_id == catalog.workspace_id))
        await session.execute(TeachingBlueprintModel.__table__.delete().where(TeachingBlueprintModel.workspace_id == catalog.workspace_id))
        for order, topic in enumerate(topics):
            session.add(CourseTopicModel(id=str(topic["id"]), workspace_id=catalog.workspace_id, name=str(topic.get("name", "")), description=str(topic.get("description", "")), status=str(topic.get("status", "enabled")), sort_order=int(topic.get("sort_order", order))))
            for kp_order, point in enumerate(topic.get("knowledge_points", [])):
                session.add(KnowledgePointModel(id=str(point["id"]), workspace_id=catalog.workspace_id, topic_id=str(topic["id"]), name=str(point.get("name", "")), markdown=str(point.get("markdown", "")), status=str(point.get("status", "enabled")), sort_order=int(point.get("sort_order", kp_order))))
        for blueprint in blueprints:
            session.add(TeachingBlueprintModel(id=str(blueprint["id"]), workspace_id=catalog.workspace_id, kind=str(blueprint.get("kind", "exercise")), topic_id=str(blueprint["topic_id"]), knowledge_point_id=blueprint.get("knowledge_point_id"), status=str(blueprint.get("status", "draft")), payload_json=blueprint, revision=int(blueprint.get("revision", 0))))
        catalog.revision += 1
        session.add(CourseCatalogVersionModel(id=str(uuid.uuid4()), workspace_id=catalog.workspace_id, revision=catalog.revision, snapshot_json={"topics": topics, "blueprints": blueprints}, change_summary=summary))


class ConversationCrud:
    async def create(self, session: AsyncSession, conversation: ConversationModel) -> ConversationModel:
        session.add(conversation)
        await session.flush()
        return conversation


class LearningCrud:
    async def create_exercise_session(self, session: AsyncSession, exercise_session: ExerciseSessionModel) -> ExerciseSessionModel:
        session.add(exercise_session)
        await session.flush()
        return exercise_session


class TurnCrud:
    async def create(self, session: AsyncSession, turn: TurnModel) -> TurnModel:
        session.add(turn)
        await session.flush()
        return turn

    async def lock_turn(self, session: AsyncSession, turn_id: str) -> TurnModel | None:
        return await session.scalar(select(TurnModel).where(TurnModel.id == turn_id).with_for_update())

    async def append_event(self, session: AsyncSession, turn: TurnModel, *, generation: int, event_type: str, payload: dict) -> TurnEventModel:
        sequence = int((await session.scalar(select(func.coalesce(func.max(TurnEventModel.sequence), 0)).where(TurnEventModel.turn_id == turn.id))) or 0) + 1
        event = TurnEventModel(id=str(uuid.uuid4()), turn_id=turn.id, sequence=sequence, claim_generation=generation, event_type=event_type, payload_json=payload)
        session.add(event)
        await session.flush()
        return event
