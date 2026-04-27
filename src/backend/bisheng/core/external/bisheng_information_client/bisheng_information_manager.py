from bisheng.core.external.bisheng_information_client.client import BishengInformationClient


async def get_bisheng_information_client() -> BishengInformationClient:
    """Get a lightweight Bisheng Information Client with the latest config."""
    from bisheng.common.services.config_service import settings
    from bisheng.core.external.http_client.http_client_manager import get_http_client
    http_client = await get_http_client()
    return BishengInformationClient(http_client=http_client, get_conf=settings.get_intelligence_center_conf)


def get_bisheng_information_client_sync() -> BishengInformationClient:
    """Get a lightweight sync Bisheng Information Client with the latest config."""
    from bisheng.common.services.config_service import settings
    return BishengInformationClient(http_client=None, get_conf=settings.get_intelligence_center_conf)
