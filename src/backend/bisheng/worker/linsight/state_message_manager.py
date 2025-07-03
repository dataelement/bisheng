from uuid import UUID

from pydantic import BaseModel

from bisheng.cache.redis import redis_client
from bisheng.database.models.linsight_session_version import SessionVersionStatusEnum, LinsightSessionVersion, \
    LinsightSessionVersionDao


class SessionVersionInfo(BaseModel):
    """会话版本信息模型"""
    id: UUID
    session_id: UUID
    user_id: UUID
    status: SessionVersionStatusEnum


class LinsightStateMessageManager(object):
    """灵思状态与消息管理器"""

    def __init__(self, session_version_id: UUID):
        """
        初始化灵思状态与消息管理器
        :param session_version_id: 会话版本ID
        """
        self._session_version_id = session_version_id
        self._redis_client = redis_client
        # redis key前缀
        self._key_prefix = f"linsight_tasks:{self._session_version_id.hex}:"
        # session_version_info key
        self._session_version_info_key = f"{self._key_prefix}session_version_info"
        # execution_tasks key
        self._execution_tasks_key = f"{self._key_prefix}execution_tasks:"

    # 写入session_version_info
    async def set_session_version_info(self, session_version_model):
        """
        设置会话版本信息
        :param session_version_model:
        """
        await LinsightSessionVersionDao.insert_one(session_version_model)

        await self._redis_client.aset(self._session_version_info_key,
                                      session_version_model.model_dump(exclude_unset=True))

    # 获取session_version_info
    async def get_session_version_info(self) -> LinsightSessionVersion | None:
        """
        获取会话版本信息
        :return: 会话版本信息模型
        """
        info = await self._redis_client.aget(self._session_version_info_key)
        if info:
            return LinsightSessionVersion.model_validate(info)
        return None
