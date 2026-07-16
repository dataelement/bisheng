from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from bisheng.common.models.config import Config
from bisheng.common.repositories.implementations.config_repository_impl import ConfigRepositoryImpl
from bisheng.core.database import get_async_db_session
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)

SHOUGANG_PORTAL_CONFIG_KEY = 'shougang_portal_config'


class ShougangPortalConfigService:
    @classmethod
    async def get_config(cls) -> ShougangPortalAdminConfig | None:
        async with get_async_db_session() as session:
            repository = ConfigRepositoryImpl(session)
            db_config = await repository.find_one(key=SHOUGANG_PORTAL_CONFIG_KEY)
            if db_config is None or not db_config.value:
                return None
            try:
                return ShougangPortalAdminConfig.model_validate_json(db_config.value)
            except ValidationError:
                logger.exception('invalid shougang portal config in config table')
                raise

    @classmethod
    async def save_config(cls, payload: ShougangPortalAdminConfig) -> ShougangPortalAdminConfig:
        normalized = ShougangPortalAdminConfig.model_validate(payload.model_dump(mode='json'))
        config_value = normalized.model_dump_json()
        async with get_async_db_session() as session:
            repository = ConfigRepositoryImpl(session)
            db_config = await repository.find_one(key=SHOUGANG_PORTAL_CONFIG_KEY)
            if db_config is None:
                await repository.save(
                    Config(
                        key=SHOUGANG_PORTAL_CONFIG_KEY,
                        value=config_value,
                        comment='Shougang portal admin aggregate config',
                    )
                )
            else:
                db_config.value = config_value
                db_config.comment = db_config.comment or 'Shougang portal admin aggregate config'
                await repository.update(db_config)
        return normalized
