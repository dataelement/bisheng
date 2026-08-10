"""SQLModel implementation of automotive sheet intro sync config repository."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.open_endpoints.domain.repositories.interfaces.automotive_sheet_intro_sync_config_repository import (
    AutomotiveSheetIntroSyncConfigRecord,
    AutomotiveSheetIntroSyncConfigRepository,
    automotive_sheet_intro_sync_physical_key,
)


class AutomotiveSheetIntroSyncConfigRepositoryImpl(AutomotiveSheetIntroSyncConfigRepository):
    _COMMENT = "Automotive sheet intro scheduled sync config"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_record(model: Config | None) -> AutomotiveSheetIntroSyncConfigRecord | None:
        if model is None:
            return None
        return AutomotiveSheetIntroSyncConfigRecord(
            key=model.key,
            value=model.value,
            comment=model.comment,
        )

    async def _find_model(self, tenant_id: int) -> Config | None:
        statement = select(Config).where(Config.key == automotive_sheet_intro_sync_physical_key(tenant_id))
        result = await self.session.exec(statement)
        return result.first()

    async def get(self, tenant_id: int) -> AutomotiveSheetIntroSyncConfigRecord | None:
        return self._to_record(await self._find_model(tenant_id))

    async def write_value(self, tenant_id: int, value: str) -> None:
        model = await self._find_model(tenant_id)
        if model is None:
            model = Config(
                key=automotive_sheet_intro_sync_physical_key(tenant_id),
                value=value,
                comment=self._COMMENT,
            )
        else:
            model.value = value
            model.comment = model.comment or self._COMMENT
        self.session.add(model)
        await self.session.flush()
