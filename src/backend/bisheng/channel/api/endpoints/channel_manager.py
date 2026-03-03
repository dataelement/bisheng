import logging

from fastapi import APIRouter, Depends

from bisheng.channel.api.dependencies import get_channel_service
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
    AddInformationSourceRequest,
    CrawlWebsiteRequest,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.core.external.bisheng_information_client.client import InformationSourceAddError

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/manager', tags=['Channel Management'])


@router.post("/create")
async def create_channel(
        req_param: CreateChannelRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Endpoint to create a new channel."""
    channel = await channel_service.create_channel(req_param, login_user)

    return resp_200(data=channel)


@router.post("/add_source")
async def add_information_source(
        req_param: AddInformationSourceRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to add a new information source by URL."""
    try:
        client = await get_bisheng_information_client()
        result = await client.add_information_source(req_param.url)
        return resp_200(data=result.model_dump())
    except InformationSourceAddError as e:
        logger.error(f"Failed to add information source: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Unexpected error adding information source: {e}")
        return resp_500(message="Failed to add information source")


@router.post("/crawl")
async def crawl_website(
        req_param: CrawlWebsiteRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to temporarily crawl a website and return its metadata."""
    try:
        client = await get_bisheng_information_client()
        result = await client.crawl_website(req_param.url)
        return resp_200(data=result.model_dump())
    except Exception as e:
        logger.error(f"Failed to crawl website: {e}")
        return resp_500(message="Failed to crawl website")
