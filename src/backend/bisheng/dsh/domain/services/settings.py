"""Read the business gate without a process-local or delayed configuration cache."""

from loguru import logger

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshDshDisabledError
from bisheng.dsh.domain.repositories.settings import DshSettingsRepository
from bisheng.dsh.domain.schemas.settings import DshManagementSettings


class DshSettingsService:
    def __init__(self, repository=None):
        self.repository = repository if repository is not None else DshSettingsRepository()

    async def read(self) -> DshManagementSettings:
        try:
            raw = await self.repository.read()
            return DshManagementSettings.model_validate_json(raw) if raw is not None else DshManagementSettings()
        except Exception:
            logger.exception("Cannot read DSH management settings")
            raise DshAuthorizationUnavailableError() from None

    async def require_enabled(self) -> None:
        if not (await self.read()).enabled:
            raise DshDshDisabledError()

    async def save(self, value: DshManagementSettings) -> DshManagementSettings:
        await self.repository.save(value.model_dump_json())
        return value
