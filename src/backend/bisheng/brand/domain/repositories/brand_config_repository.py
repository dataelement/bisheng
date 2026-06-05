from typing import Optional

from bisheng.common.models.config import Config, ConfigDao


class BrandConfigRepository:
    """Persistence adapter for instance-level brand config."""

    async def get_value(self, key: str) -> Optional[str]:
        config = await ConfigDao.aget_config_by_key(key)
        return config.value if config else None

    async def upsert_value(self, key: str, value: str) -> Config:
        return await ConfigDao.insert_or_update_config(key, value)
