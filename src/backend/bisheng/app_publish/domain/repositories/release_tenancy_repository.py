"""Bounded reads of the exact deployment, its application and its optional version."""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.app_publish.domain.models.app_deployment import AppDeployment
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion


@dataclass(frozen=True, slots=True)
class ReleaseRecords:
    app: App
    deployment: AppDeployment
    version: AppVersion | None


class ReleaseTenancyRepository:
    @classmethod
    async def load(
        cls,
        app_id: str,
        *,
        version_id: str | None = None,
        deployment_id: str | None = None,
    ) -> ReleaseRecords | None:
        if not app_id or not (deployment_id or version_id):
            return None
        query = select(AppDeployment).where(AppDeployment.app_id == app_id)
        if deployment_id:
            query = query.where(AppDeployment.id == deployment_id)
        if version_id:
            query = query.where(AppDeployment.version_id == version_id)
        async with get_async_db_session() as session:
            deployments = (await session.exec(query.limit(2))).all()
            if len(deployments) != 1:
                return None
            deployment = deployments[0]
            app = (await session.exec(select(App).where(App.id == app_id))).first()
            if app is None:
                return None
            version = (
                await session.exec(
                    select(AppVersion).where(AppVersion.app_id == app_id, AppVersion.id == deployment.version_id)
                )
            ).first()
        return ReleaseRecords(app=app, deployment=deployment, version=version)
