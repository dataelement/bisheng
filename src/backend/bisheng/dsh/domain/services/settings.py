"""Read access addresses with business access enabled for deployed DSH."""

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
            value = DshManagementSettings.model_validate_json(raw) if raw is not None else DshManagementSettings()
            return value.model_copy(update={"enabled": True})
        except Exception:
            logger.exception("Cannot read DSH management settings")
            raise DshAuthorizationUnavailableError() from None

    async def require_enabled(self) -> None:
        if not (await self.read()).enabled:
            raise DshDshDisabledError()

    async def platform_public_url(self, fallback: str | None) -> str | None:
        """The administrator-managed origin wins; null keeps the deployment value."""
        try:
            stored = (await self.read()).platform_public_url
        except DshAuthorizationUnavailableError:
            logger.warning("DSH settings unreadable; falling back to the deployment public URL")
            return fallback
        return stored or fallback

    async def save(self, value: DshManagementSettings) -> DshManagementSettings:
        value = value.model_copy(update={"enabled": True})
        await self.repository.save(value.model_dump_json())
        return value
