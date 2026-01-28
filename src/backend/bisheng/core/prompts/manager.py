import logging
from abc import ABC

from bisheng.core.context import BaseContextManager
from bisheng.core.prompts.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class PromptManager(BaseContextManager[PromptLoader]):
    """Prompt Manager

    Responsible for loading, caching, and managing prompts
    """

    name = 'prompts'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _async_initialize(self) -> PromptLoader:
        """Asynchronous initialization prompt word loader"""
        logger.info("Initializing PromptLoader...")
        prompt_loader = PromptLoader()
        logger.info("PromptLoader initialized.")
        return prompt_loader

    def _sync_initialize(self) -> PromptLoader:
        """Synchronous Initialization Prompt Loader"""
        logger.info("Initializing PromptLoader...")
        prompt_loader = PromptLoader()
        logger.info("PromptLoader initialized.")
        return prompt_loader

    async def _async_cleanup(self) -> None:
        """Clean up database resources"""
        pass

    def _sync_cleanup(self) -> None:
        """Synchronously clean up database resources"""
        pass


async def get_prompt_manager() -> PromptLoader:
    """Get a prompt word manager instance (asynchronous)"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(PromptManager.name)
    except KeyError:
        logger.warning(f"PromptManager not found in context. Registering...")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(PromptManager())
            return await  app_context.async_get_instance(PromptManager.name)
        except Exception as e:
            logger.error(f"Failed to register PromptManager: {e}")
            raise


def get_prompt_manager_sync() -> PromptLoader:
    """Get a prompt word manager instance (sync method)"""
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
