from abc import ABC

from bisheng.common.models.config import Config
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ConfigRepository(BaseRepository[Config, str], ABC):
    """配置仓库接口"""
    pass
