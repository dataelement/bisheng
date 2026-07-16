"""Transaction-friendly aggregate portal configuration repository."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
    PortalAdminConfigRecord,
    PortalAdminConfigRepository,
    portal_admin_config_physical_key,
)


class PortalAdminConfigRepositoryImpl(PortalAdminConfigRepository):
    _COMMENT = "Shougang portal admin aggregate config"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_record(model: Config | None) -> PortalAdminConfigRecord | None:
        if model is None:
            return None
        return PortalAdminConfigRecord(
            key=model.key,
            value=model.value,
            comment=model.comment,
        )

    async def _find_model(self, tenant_id: int, *, for_update: bool) -> Config | None:
        statement = select(Config).where(Config.key == portal_admin_config_physical_key(tenant_id))
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.exec(statement)
        return result.first()

    async def get(self, tenant_id: int) -> PortalAdminConfigRecord | None:
        return self._to_record(await self._find_model(tenant_id, for_update=False))

    async def get_for_update(self, tenant_id: int) -> PortalAdminConfigRecord | None:
        return self._to_record(await self._find_model(tenant_id, for_update=True))

    async def write_value(self, tenant_id: int, value: str) -> None:
        model = await self._find_model(tenant_id, for_update=False)
        if model is None:
            model = Config(
                key=portal_admin_config_physical_key(tenant_id),
                value=value,
                comment=self._COMMENT,
            )
        else:
            model.value = value
            model.comment = model.comment or self._COMMENT
        self.session.add(model)
        await self.session.flush()
