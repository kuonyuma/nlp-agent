from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from core.identity import AuthenticatedPrincipal
from core.rbac import Permission, authorization_service
from server.teacher.analytics import build_analytics
from server.teacher.models import (
    ExerciseBlueprint,
    GuidedBlueprint,
    LearningBookNavigationItem,
    LearningBookPage,
    ReviewBlueprint,
    TeacherBookImportApplyRequest,
    TeacherBookImportPreview,
    TeacherBookImportPreviewRequest,
    TeacherBookNavigationItem,
    TeacherBookPage,
    TeacherCatalog,
    TeachingGoals,
    UpdateTeacherBookPage,
    UpdateTeacherCatalog,
    UpdateTeachingGoals,
    PublishTeacherBookPage,
)
from server.teacher.content import normalize_teacher_markdown


class TeacherService:
    @staticmethod
    def require_teacher(
        principal: AuthenticatedPrincipal,
        workspace_id: str,
        permission: Permission = Permission.LEARNING_CONTENT_MANAGE,
    ) -> None:
        authorization_service.require(
            principal,
            permission,
            workspace_id=workspace_id,
        )

    async def goals(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        settings = await gateway.get_user_settings(principal)
        key = f"teacher_goals:{workspace_id}"
        value = settings["settings"].get(key) or TeachingGoals(workspace_id=workspace_id).model_dump(mode="json")
        return {"goals": value, "revision": settings["revision"], "updated_at": settings["updated_at"]}

    async def update_goals(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, body: UpdateTeachingGoals) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        goals = TeachingGoals(workspace_id=workspace_id, **body.model_dump()).model_dump(mode="json")
        result = await gateway.update_user_settings(principal, {f"teacher_goals:{workspace_id}": goals})
        return {"goals": goals, "revision": result["revision"], "updated_at": result["updated_at"]}

    async def catalog(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str) -> dict[str, Any]:
        self.require_teacher(
            principal, workspace_id, Permission.LEARNING_PROGRESS_READ_CLASSROOM
        )
        result = await gateway.get_teaching_catalog(principal, workspace_id)
        value = TeacherCatalog.model_validate(result["catalog"])
        return {"catalog": value.model_dump(mode="json"), "revision": result["revision"], "updated_at": result["updated_at"]}

    async def update_catalog(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, body: UpdateTeacherCatalog) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        value = TeacherCatalog(workspace_id=workspace_id, **body.model_dump())
        self._validate_blueprint_links(value)
        catalog = value.model_dump(mode="json")
        result = await gateway.update_teaching_catalog(principal, workspace_id, catalog)
        return {"catalog": catalog, "revision": result["revision"], "updated_at": result["updated_at"]}

    @staticmethod
    def _catalog_point(catalog: TeacherCatalog, knowledge_point_id: str) -> tuple[Any, Any]:
        for topic in catalog.topics:
            for point in topic.knowledge_points:
                if point.id == knowledge_point_id:
                    return topic, point
        raise FileNotFoundError(knowledge_point_id)

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else value

    @classmethod
    def _teacher_book_page(
        cls,
        workspace_id: str,
        topic: Any,
        point: Any,
        row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return TeacherBookPage(
            workspace_id=workspace_id,
            topic_id=topic.id,
            topic_name=topic.name,
            knowledge_point_id=point.id,
            title=point.name,
            draft_markdown=str(row.get("draft_markdown", "")) if row else "",
            published_markdown=row.get("published_markdown") if row else None,
            revision=int(row.get("revision", 0)) if row else 0,
            published_revision=(
                int(row["published_revision"])
                if row and row.get("published_revision") is not None
                else None
            ),
            updated_at=cls._timestamp(row.get("updated_at")) if row else None,
        ).model_dump(mode="json")

    async def teacher_book_navigation(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id, Permission.LEARNING_PROGRESS_READ_CLASSROOM)
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        rows = await gateway.list_knowledge_pages(principal, workspace_id)
        pages = {str(row["knowledge_point_id"]): row for row in rows}
        items: list[dict[str, Any]] = []
        for topic in catalog.topics:
            for point in topic.knowledge_points:
                row = pages.get(point.id)
                item = TeacherBookNavigationItem(
                    topic_id=topic.id,
                    topic_name=topic.name,
                    knowledge_point_id=point.id,
                    title=point.name,
                    sort_order=point.sort_order,
                    topic_status=topic.status,
                    knowledge_point_status=point.status,
                    has_draft=bool(row and str(row.get("draft_markdown", "")).strip()),
                    has_published=bool(row and row.get("published_markdown") is not None),
                    revision=int(row.get("revision", 0)) if row else 0,
                    published_revision=(
                        int(row["published_revision"])
                        if row and row.get("published_revision") is not None
                        else None
                    ),
                )
                items.append(item.model_dump(mode="json"))
        return {"workspace_id": workspace_id, "items": items}

    async def teacher_book_page(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, knowledge_point_id: str) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id, Permission.LEARNING_PROGRESS_READ_CLASSROOM)
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        topic, point = self._catalog_point(catalog, knowledge_point_id)
        row = await gateway.get_knowledge_page(principal, workspace_id, knowledge_point_id)
        return {"page": self._teacher_book_page(workspace_id, topic, point, row)}

    async def learning_book_navigation(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str) -> dict[str, Any]:
        authorization_service.require(
            principal, Permission.LEARNING_CONTENT_READ_WORKSPACE, workspace_id=workspace_id
        )
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        rows = await gateway.list_knowledge_pages(principal, workspace_id)
        pages = {str(row["knowledge_point_id"]): row for row in rows}
        items: list[dict[str, Any]] = []
        for topic in catalog.topics:
            if topic.status != "enabled":
                continue
            for point in topic.knowledge_points:
                row = pages.get(point.id)
                if point.status != "enabled" or not row or row.get("published_markdown") is None:
                    continue
                items.append(
                    LearningBookNavigationItem(
                        topic_id=topic.id,
                        topic_name=topic.name,
                        knowledge_point_id=point.id,
                        title=point.name,
                        sort_order=point.sort_order,
                        revision=int(row["revision"]),
                    ).model_dump(mode="json")
                )
        return {"workspace_id": workspace_id, "items": items}

    async def learning_book_page(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, knowledge_point_id: str) -> dict[str, Any]:
        authorization_service.require(
            principal, Permission.LEARNING_CONTENT_READ_WORKSPACE, workspace_id=workspace_id
        )
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        topic, point = self._catalog_point(catalog, knowledge_point_id)
        if topic.status != "enabled" or point.status != "enabled":
            raise FileNotFoundError(knowledge_point_id)
        row = await gateway.get_published_knowledge_page(principal, workspace_id, knowledge_point_id)
        if row is None:
            raise FileNotFoundError(knowledge_point_id)
        page = LearningBookPage(
            workspace_id=workspace_id,
            topic_id=topic.id,
            topic_name=topic.name,
            knowledge_point_id=point.id,
            title=point.name,
            content_markdown=str(row["published_markdown"]),
            revision=int(row["published_revision"] or row["revision"]),
        )
        return {"page": page.model_dump(mode="json")}

    async def update_teacher_book_page(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, knowledge_point_id: str, body: UpdateTeacherBookPage) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        topic, point = self._catalog_point(catalog, knowledge_point_id)
        normalized = normalize_teacher_markdown("page.md", body.content_markdown)
        row = await gateway.update_knowledge_page(
            principal, workspace_id, knowledge_point_id, normalized.content_markdown,
            expected_revision=body.expected_revision,
        )
        return {"page": self._teacher_book_page(workspace_id, topic, point, row)}

    async def publish_teacher_book_page(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, knowledge_point_id: str, body: PublishTeacherBookPage) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        topic, point = self._catalog_point(catalog, knowledge_point_id)
        row = await gateway.publish_knowledge_page(
            principal, workspace_id, knowledge_point_id, expected_revision=body.expected_revision
        )
        return {"page": self._teacher_book_page(workspace_id, topic, point, row)}

    async def preview_teacher_book_import(self, principal: AuthenticatedPrincipal, workspace_id: str, body: TeacherBookImportPreviewRequest) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        return normalize_teacher_markdown(body.file_name, body.content_markdown).model_dump(mode="json")

    async def apply_teacher_book_import(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, body: TeacherBookImportApplyRequest) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(
            (await gateway.get_teaching_catalog(principal, workspace_id))["catalog"]
        )
        topic, point = self._catalog_point(catalog, body.knowledge_point_id)
        normalized = normalize_teacher_markdown(body.file_name, body.content_markdown)
        row = await gateway.update_knowledge_page(
            principal, workspace_id, body.knowledge_point_id, normalized.content_markdown,
            expected_revision=body.expected_revision,
        )
        return {"page": self._teacher_book_page(workspace_id, topic, point, row)}

    @staticmethod
    def _validate_blueprint_links(catalog: TeacherCatalog) -> None:
        points = {
            (topic.id, point.id)
            for topic in catalog.topics
            for point in topic.knowledge_points
        }
        exercise_ids = {blueprint.id: blueprint for blueprint in catalog.exercise_blueprints}
        for blueprint in [*catalog.exercise_blueprints, *catalog.review_blueprints, *catalog.guided_blueprints]:
            if (blueprint.topic_id, blueprint.knowledge_point_id) not in points:
                raise ValueError("蓝图必须关联其所属主题中的一个知识点")
            if blueprint.status == "enabled" and not isinstance(blueprint, GuidedBlueprint):
                if not blueprint.rubric:
                    raise ValueError("启用蓝图前必须至少配置一个评分标准")
                for point in blueprint.rubric:
                    criterion = str(point.get("criterion", "")).strip()
                    try:
                        weight = float(point.get("weight", 0))
                    except (TypeError, ValueError):
                        weight = 0
                    if not criterion or weight <= 0:
                        raise ValueError("启用蓝图的每个评分标准都必须填写内容并设置正权重")
        for blueprint in catalog.review_blueprints:
            if blueprint.exercise_blueprint_id is None:
                continue
            target = exercise_ids.get(blueprint.exercise_blueprint_id)
            if target is None or (target.topic_id, target.knowledge_point_id) != (blueprint.topic_id, blueprint.knowledge_point_id):
                raise ValueError("复习蓝图关联的练习蓝图必须属于同一主题和知识点")

    async def upsert_exercise_blueprint(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, blueprint: ExerciseBlueprint) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        current = await gateway.get_teaching_catalog(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(current["catalog"])
        items = [item for item in catalog.exercise_blueprints if item.id != blueprint.id]
        updated = UpdateTeacherCatalog(
            topics=catalog.topics, exercise_blueprints=[*items, blueprint], review_blueprints=catalog.review_blueprints, guided_blueprints=catalog.guided_blueprints,
        )
        return await self.update_catalog(principal, gateway, workspace_id, updated)

    async def upsert_review_blueprint(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, blueprint: ReviewBlueprint) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        current = await gateway.get_teaching_catalog(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(current["catalog"])
        items = [item for item in catalog.review_blueprints if item.id != blueprint.id]
        updated = UpdateTeacherCatalog(
            topics=catalog.topics, exercise_blueprints=catalog.exercise_blueprints, review_blueprints=[*items, blueprint], guided_blueprints=catalog.guided_blueprints,
        )
        return await self.update_catalog(principal, gateway, workspace_id, updated)

    async def upsert_guided_blueprint(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, blueprint: GuidedBlueprint) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        current = await gateway.get_teaching_catalog(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(current["catalog"])
        items = [item for item in catalog.guided_blueprints if item.id != blueprint.id]
        updated = UpdateTeacherCatalog(
            topics=catalog.topics, exercise_blueprints=catalog.exercise_blueprints,
            review_blueprints=catalog.review_blueprints, guided_blueprints=[*items, blueprint],
        )
        return await self.update_catalog(principal, gateway, workspace_id, updated)

    async def delete_blueprint(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, blueprint_id: str, *, kind: str) -> dict[str, Any]:
        self.require_teacher(principal, workspace_id)
        current = await gateway.get_teaching_catalog(principal, workspace_id)
        catalog = TeacherCatalog.model_validate(current["catalog"])
        body = UpdateTeacherCatalog(
            topics=catalog.topics,
            exercise_blueprints=[item for item in catalog.exercise_blueprints if item.id != blueprint_id] if kind == "exercise" else catalog.exercise_blueprints,
            review_blueprints=[item for item in catalog.review_blueprints if item.id != blueprint_id] if kind == "review" else catalog.review_blueprints,
            guided_blueprints=[item for item in catalog.guided_blueprints if item.id != blueprint_id] if kind == "guided" else catalog.guided_blueprints,
        )
        return await self.update_catalog(principal, gateway, workspace_id, body)

    async def analytics(self, principal: AuthenticatedPrincipal, gateway: Any, workspace_id: str, days: int = 30) -> dict[str, Any]:
        self.require_teacher(
            principal, workspace_id, Permission.LEARNING_PROGRESS_READ_CLASSROOM
        )
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        catalog = (await asyncio.to_thread(gateway.repository.get_teaching_catalog, workspace_id))["catalog"]
        question_rows = await asyncio.to_thread(gateway.repository.list_question_turns, workspace_id=workspace_id, since=since)
        evidence_rows = await asyncio.to_thread(gateway.repository.exercise_evidence_stats, workspace_id=workspace_id, since=since)
        criterion_rows = await asyncio.to_thread(gateway.repository.exercise_criterion_stats, workspace_id=workspace_id, since=since)
        guided_rows = await asyncio.to_thread(gateway.repository.guided_session_stats, workspace_id=workspace_id, since=since)
        result = build_analytics(question_rows, evidence_rows, criterion_rows, guided_rows, catalog)
        return {"workspace_id": workspace_id, "period_days": days, **result}


teacher_service = TeacherService()
