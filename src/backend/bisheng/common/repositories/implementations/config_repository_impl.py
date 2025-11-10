from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.common.repositories.interfaces.config_repository import ConfigRepository


class ConfigRepositoryImpl(BaseRepositoryImpl[Config, str], ConfigRepository):
    """共享链接仓库实现"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Config)
