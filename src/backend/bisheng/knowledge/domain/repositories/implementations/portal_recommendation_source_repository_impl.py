"""Bounded current-file queries for recommendation projection maintenance."""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_source_repository import (
    PortalRecommendationSourceRepository,
)
from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
    PortalRecommendationSourceFile,
)


class PortalRecommendationSourceRepositoryImpl(PortalRecommendationSourceRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_source(row) -> PortalRecommendationSourceFile:
        file, is_primary = row
        return PortalRecommendationSourceFile(
            file_id=int(file.id),
            space_id=int(file.knowledge_id),
            file_type=int(file.file_type),
            status=int(file.status) if file.status is not None else None,
            split_rule=file.split_rule,
            file_encoding=file.file_encoding,
            file_level_path=file.file_level_path,
            source_update_time=file.update_time or file.create_time,
            is_primary=bool(is_primary) if is_primary is not None else None,
        )

    @staticmethod
    def _statement():
        return select(KnowledgeFile, KnowledgeDocumentVersion.is_primary).outerjoin(
            KnowledgeDocumentVersion,
            KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id,
        )

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    async def find_by_id(self, file_id: int) -> PortalRecommendationSourceFile | None:
        rows = await self._list(self._statement().where(KnowledgeFile.id == int(file_id)).limit(1))
        return rows[0] if rows else None

    async def find_by_ids(self, file_ids: Sequence[int]) -> list[PortalRecommendationSourceFile]:
        normalized_ids = sorted({int(file_id) for file_id in file_ids})
        if not normalized_ids:
            return []
        return await self._list(
            self._statement()
            .where(col(KnowledgeFile.id).in_(normalized_ids))
            .order_by(KnowledgeFile.id)
        )

    async def list_changed_after(
        self,
        *,
        update_time: datetime,
        file_id: int,
        limit: int,
    ) -> list[PortalRecommendationSourceFile]:
        # KnowledgeFile.update_time is a timezone-naive UTC DATETIME in MySQL/DM8.
        # Keep the comparison parameter equally naive to avoid dialect-specific
        # aware-datetime coercion while preserving the UTC watermark semantics.
        update_time = self._naive_utc(update_time)
        return await self._list(
            self._statement()
            .where(
                or_(
                    KnowledgeFile.update_time > update_time,
                    and_(KnowledgeFile.update_time == update_time, KnowledgeFile.id > int(file_id)),
                )
            )
            .order_by(KnowledgeFile.update_time, KnowledgeFile.id)
            .limit(self._validated_limit(limit))
        )

    async def list_page(self, *, after_id: int, limit: int) -> list[PortalRecommendationSourceFile]:
        return await self._list(
            self._statement()
            .where(KnowledgeFile.id > int(after_id))
            .order_by(KnowledgeFile.id)
            .limit(self._validated_limit(limit))
        )

    async def list_for_resource(
        self,
        resource_type: str,
        resource_id: int,
        *,
        after_id: int,
        limit: int,
    ) -> list[PortalRecommendationSourceFile]:
        resource_type = str(resource_type)
        resource_id = int(resource_id)
        statement = self._statement().where(
            KnowledgeFile.id > int(after_id),
            KnowledgeFile.file_type == 1,
        )
        if resource_type == "knowledge_file":
            statement = statement.where(KnowledgeFile.id == resource_id)
        elif resource_type == "folder":
            statement = statement.where(
                or_(
                    col(KnowledgeFile.file_level_path).like(f"%/{resource_id}"),
                    col(KnowledgeFile.file_level_path).like(f"%/{resource_id}/%"),
                )
            )
        elif resource_type in {"knowledge_space", "knowledge_library"}:
            statement = statement.where(KnowledgeFile.knowledge_id == resource_id)
        else:
            raise ValueError("unsupported recommendation projection resource type")
        return await self._list(
            statement.order_by(KnowledgeFile.id).limit(self._validated_limit(limit))
        )

    async def _list(self, statement) -> list[PortalRecommendationSourceFile]:
        with strict_tenant_filter():
            result = await self.session.exec(statement)
        return [self._to_source(row) for row in result.all()]

    @staticmethod
    def _validated_limit(limit: int) -> int:
        value = int(limit)
        if value <= 0:
            raise ValueError("limit must be positive")
        return value
