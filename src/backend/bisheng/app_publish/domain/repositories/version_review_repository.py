"""Tenant-scoped deployment reads for approval status projections."""

from sqlmodel import col, select

from bisheng.app_publish.domain.models.app_deployment import AppDeployment
from bisheng.core.database import get_async_db_session


class VersionReviewRepository:
    @staticmethod
    async def deployments(app_id: str, tenant_id: int, version_ids: list[str]) -> list[AppDeployment]:
        rows = []
        async with get_async_db_session() as session:
            for offset in range(0, len(version_ids), 100):
                query = select(AppDeployment).where(
                    AppDeployment.app_id == app_id,
                    AppDeployment.tenant_id == tenant_id,
                    col(AppDeployment.version_id).in_(version_ids[offset : offset + 100]),
                )
                rows.extend((await session.exec(query)).all())
        return rows

    @staticmethod
    async def latest(app_id: str) -> AppDeployment | None:
        query = (
            select(AppDeployment)
            .where(AppDeployment.app_id == app_id)
            .order_by(col(AppDeployment.create_time).desc(), col(AppDeployment.id).desc())
            .limit(1)
        )
        async with get_async_db_session() as session:
            return (await session.exec(query)).first()
