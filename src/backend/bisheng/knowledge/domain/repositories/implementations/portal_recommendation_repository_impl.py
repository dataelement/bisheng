"""SQLModel implementation of the portal recommendation projection repository."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_repository import (
    PortalRecommendationProjectionRecord,
    PortalRecommendationProjectionUpsert,
    PortalRecommendationRepository,
)


class PortalRecommendationRepositoryImpl(PortalRecommendationRepository):
    _PERMISSION_SCOPES = frozenset({"inherited", "custom", "unknown"})

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_record(model: PortalRecommendationFileProjection) -> PortalRecommendationProjectionRecord:
        return PortalRecommendationProjectionRecord(
            id=int(model.id),
            tenant_id=int(model.tenant_id),
            file_id=int(model.file_id),
            space_id=int(model.space_id),
            business_domain_code=model.business_domain_code,
            permission_scope=model.permission_scope,
            recommendable=bool(model.recommendable),
            reason_code=model.reason_code,
            source_update_time=model.source_update_time,
            projection_version=int(model.projection_version),
        )

    @classmethod
    def _validated_values(cls, value: PortalRecommendationProjectionUpsert) -> dict:
        permission_scope = str(value.permission_scope or "").strip().lower()
        if permission_scope not in cls._PERMISSION_SCOPES:
            raise ValueError("permission_scope must be inherited, custom or unknown")
        business_domain_code = str(value.business_domain_code or "").strip().upper() or None
        reason_code = str(value.reason_code or "").strip().lower()
        if not reason_code:
            raise ValueError("reason_code is required")
        if int(value.projection_version) < 0:
            raise ValueError("projection_version must be non-negative")
        return {
            "file_id": int(value.file_id),
            "space_id": int(value.space_id),
            "business_domain_code": business_domain_code,
            "permission_scope": permission_scope,
            "recommendable": int(bool(value.recommendable)),
            "reason_code": reason_code,
            "source_update_time": value.source_update_time,
            "projection_version": int(value.projection_version),
        }

    async def upsert(self, value: PortalRecommendationProjectionUpsert) -> bool:
        values = self._validated_values(value)
        with strict_tenant_filter():
            result = await self.session.exec(
                select(PortalRecommendationFileProjection)
                .where(PortalRecommendationFileProjection.file_id == values["file_id"])
                .with_for_update()
            )
        model = result.first()
        if model is not None and int(model.projection_version) >= values["projection_version"]:
            return False
        if model is None:
            model = PortalRecommendationFileProjection(**values)
        else:
            for field, field_value in values.items():
                setattr(model, field, field_value)
        self.session.add(model)
        await self.session.flush()
        return True

    async def delete(self, file_id: int, projection_version: int) -> bool:
        event_version = max(int(projection_version), 0)
        with strict_tenant_filter():
            result = await self.session.exec(
                select(PortalRecommendationFileProjection)
                .where(PortalRecommendationFileProjection.file_id == int(file_id))
                .with_for_update()
            )
        model = result.first()
        if model is None:
            return False
        if int(model.projection_version) > event_version:
            return False
        await self.session.delete(model)
        await self.session.flush()
        return True

    async def find_by_file_ids(
        self,
        file_ids: Sequence[int],
    ) -> list[PortalRecommendationProjectionRecord]:
        normalized_ids = sorted({int(value) for value in file_ids})
        if not normalized_ids:
            return []
        statement = select(PortalRecommendationFileProjection).where(
            col(PortalRecommendationFileProjection.file_id).in_(normalized_ids)
        )
        return await self._list(statement)

    async def list_recommendable_by_domains(
        self,
        business_domain_codes: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
        space_ids: Sequence[int] | None = None,
    ) -> list[PortalRecommendationProjectionRecord]:
        domain_codes = sorted({str(value).strip().upper() for value in business_domain_codes if str(value).strip()})
        if not domain_codes:
            return []
        statement = (
            select(PortalRecommendationFileProjection)
            .where(
                PortalRecommendationFileProjection.recommendable == 1,
                col(PortalRecommendationFileProjection.business_domain_code).in_(domain_codes),
            )
            .order_by(
                PortalRecommendationFileProjection.source_update_time.desc(),
                PortalRecommendationFileProjection.file_id.desc(),
            )
        )
        if space_ids is not None:
            normalized_space_ids = sorted({int(value) for value in space_ids})
            if not normalized_space_ids:
                return []
            statement = statement.where(
                col(PortalRecommendationFileProjection.space_id).in_(normalized_space_ids)
            )
        statement = statement.offset(max(int(offset), 0)).limit(self._validated_limit(limit))
        return await self._list(statement)

    async def list_latest_recommendable(
        self,
        *,
        space_ids: Sequence[int] | None,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        statement = select(PortalRecommendationFileProjection).where(
            PortalRecommendationFileProjection.recommendable == 1
        )
        if space_ids is not None:
            normalized_space_ids = sorted({int(value) for value in space_ids})
            if not normalized_space_ids:
                return []
            statement = statement.where(col(PortalRecommendationFileProjection.space_id).in_(normalized_space_ids))
        statement = statement.order_by(
            PortalRecommendationFileProjection.source_update_time.desc(),
            PortalRecommendationFileProjection.file_id.desc(),
        ).limit(self._validated_limit(limit))
        return await self._list(statement)

    async def list_changed_after(
        self,
        *,
        update_time: datetime,
        file_id: int,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        statement = (
            select(PortalRecommendationFileProjection)
            .where(
                or_(
                    PortalRecommendationFileProjection.update_time > update_time,
                    and_(
                        PortalRecommendationFileProjection.update_time == update_time,
                        PortalRecommendationFileProjection.file_id > int(file_id),
                    ),
                )
            )
            .order_by(
                PortalRecommendationFileProjection.update_time,
                PortalRecommendationFileProjection.file_id,
            )
            .limit(self._validated_limit(limit))
        )
        return await self._list(statement)

    async def list_page(
        self,
        *,
        after_id: int,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        statement = (
            select(PortalRecommendationFileProjection)
            .where(PortalRecommendationFileProjection.id > int(after_id))
            .order_by(PortalRecommendationFileProjection.id)
            .limit(self._validated_limit(limit))
        )
        return await self._list(statement)

    async def _list(self, statement) -> list[PortalRecommendationProjectionRecord]:
        with strict_tenant_filter():
            result = await self.session.exec(statement)
        return [self._to_record(model) for model in result.all()]

    @staticmethod
    def _validated_limit(limit: int) -> int:
        value = int(limit)
        if value <= 0:
            raise ValueError("limit must be positive")
        return value
