from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.context import BaseContextManager
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient


class BishengInformationManager(BaseContextManager[BishengInformationClient]):
    """Bisheng Information Manager

    Inherited From BaseContextManagerProvided by Bisheng Information Client lifecycle management
    Supports lazy loading and caching
    """

    name = 'bisheng_information_client'

    def __init__(self, http_client, intelligence_center_conf: IntelligenceCenterConf):
        super().__init__()
        self.http_client = http_client
        self.intelligence_center_conf = intelligence_center_conf

    async def _async_initialize(self) -> BishengInformationClient:
        """Async Initialization Bisheng Information Client"""
        return BishengInformationClient(self.http_client, self.intelligence_center_conf.base_url,
                                        self.intelligence_center_conf.api_key)

    def _sync_initialize(self) -> BishengInformationClient:
        """Sync Initialization Bisheng Information Client"""
        return BishengInformationClient(self.http_client, self.intelligence_center_conf.base_url,
                                        self.intelligence_center_conf.api_key)

    async def _async_cleanup(self) -> None:
        """Asynchronous Cleanup Bisheng Information Client"""
        pass

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Bisheng Information Client"""
        pass


async def get_bisheng_information_client() -> BishengInformationClient:
    """Dapatkan Bisheng Information Client Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(BishengInformationManager.name)
    except KeyError:
        from bisheng.common.services.config_service import settings
        from bisheng.core.external.http_client.http_client_manager import get_http_client
        http_client = await get_http_client()
        config = await settings.aget_intelligence_center_conf()
        app_context.register_context(
            BishengInformationManager(http_client, config)
        )
        return await app_context.async_get_instance(BishengInformationManager.name)
