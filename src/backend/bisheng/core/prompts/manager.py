import logging
from abc import ABC

from bisheng.core.context import BaseContextManager
from bisheng.core.prompts.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class PromptManager(BaseContextManager[PromptLoader], ABC):
    """提示词管理器

    负责提示词的加载、缓存和管理
    """

    name = 'prompts'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _async_initialize(self) -> PromptLoader:
        """异步初始化提示词加载器"""
        logger.info("Initializing PromptLoader...")
        prompt_loader = PromptLoader()
        logger.info("PromptLoader initialized.")
        return prompt_loader

    def _sync_initialize(self) -> PromptLoader:
        """同步初始化提示词加载器"""
        logger.info("Initializing PromptLoader...")
        prompt_loader = PromptLoader()
        logger.info("PromptLoader initialized.")
        return prompt_loader

    async def _async_cleanup(self) -> None:
        """清理数据库资源"""
        pass

    def _sync_cleanup(self) -> None:
        """同步清理数据库资源"""
        pass


async def get_prompt_manager() -> PromptLoader:
    """获取提示词管理器实例（异步方式）"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.async_get_instance(PromptManager.name)
    except KeyError:
        logger.warning(f"PromptManager not found in context. Registering...")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(PromptManager())
            return app_context.async_get_instance(PromptManager.name)
        except Exception as e:
            logger.error(f"Failed to register PromptManager: {e}")
            raise


def get_prompt_manager_sync() -> PromptLoader:
    """获取提示词管理器实例（同步方式）"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(PromptManager.name)
    except KeyError:
        logger.warning(f"PromptManager not found in context. Registering...")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(PromptManager())
            return app_context.sync_get_instance(PromptManager.name)
        except Exception as e:
            logger.error(f"Failed to register PromptManager: {e}")
            raise
