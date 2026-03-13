import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.channel.api.dependencies import get_channel_service
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
    UpdateChannelRequest,
    AddInformationSourceRequest,
    CrawlWebsiteRequest,
    MyChannelQueryRequest,
    SetPinRequest,
    UpdateMemberRoleRequest,
    RemoveMemberRequest,
    QueryTypeEnum,
    SortByEnum,
    SubscribeChannelRequest,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.core.external.bisheng_information_client.client import InformationSourceAddError, BusinessType

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


@router.get("/list_sources")
async def list_channel_information_sources(
        business_type: BusinessType = Query(..., description='Information source type: website / wechat'),
        page: int = Query(1, ge=1, description='Page number, default 1'),
        page_size: int = Query(20, ge=1, le=100, description='Page size, default 20'),
        login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Endpoint to list information sources of a channel."""

    client = await get_bisheng_information_client()
    sources, total = await client.list_information_sources(business_type=business_type, page=page,
                                                           page_size=page_size)
    return resp_200(data={
        "sources": [s.model_dump() for s in sources],
        "total": total
    })


@router.get("/search_sources")
async def search_channel_information_sources(
        keyword: str = Query(..., min_length=1, description='Search keyword, fuzzy match name and URL'),
        business_type: Optional[BusinessType] = Query(None, description='Information source type: website / wechat'),
        page: int = Query(1, ge=1, description='Page number, default 1'),
        page_size: int = Query(20, ge=1, le=100, description='Page size, default 20'),
        login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Endpoint to search information sources of a channel by keyword."""
    client = await get_bisheng_information_client()
    sources, total = await client.search_information_sources(
        query=keyword,
        business_type=business_type,
        page=page,
        page_size=page_size
    )
    return resp_200(data={
        "sources": [s.model_dump() for s in sources],
        "total": total
    })


@router.post("/add_website_source")
async def add_website_information_source(
        req_param: AddInformationSourceRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to add a new information source by URL."""
    client = await get_bisheng_information_client()
    result = await client.add_website_information_source(req_param.url)
    return resp_200(data=result.model_dump())



@router.post("/add_wechat_source")
async def add_wechat_information_source(
        req_param: AddInformationSourceRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to add a new WeChat information source by URL."""
    client = await get_bisheng_information_client()
    result = await client.add_wechat_information_source(req_param.url)
    return resp_200(data=result.model_dump())



@router.post("/crawl")
async def crawl_website(
        req_param: CrawlWebsiteRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to temporarily crawl a website and return its metadata."""

    client = await get_bisheng_information_client()
    result = await client.crawl_website(req_param.url)
    return resp_200(data=result.model_dump())


@router.get("/my_channels")
async def get_my_channels(
        query_type: QueryTypeEnum = Query(..., description='Query type: created / followed'),
        sort_by: SortByEnum = Query(SortByEnum.LATEST_UPDATE, description='Sort by, default latest update'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Endpoint to get channels related to the logged-in user, either created or followed, with sorting options."""
    query_data = MyChannelQueryRequest(query_type=query_type, sort_by=sort_by)
    result = await channel_service.get_my_channels(query_data, login_user)
    return resp_200(data=[item.model_dump() for item in result])


@router.get("/square")
async def get_channel_square(
        keyword: Optional[str] = Query(None, description='Fuzzy search keyword (channel name/description)'),
        page: int = Query(1, ge=1, description='Page number, default 1'),
        page_size: int = Query(20, ge=1, le=100, description='Page size, default 20'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Channel square query: Paginated query of all released channels, supports fuzzy search, displays subscription status and subscriber count."""
    try:
        result = await channel_service.get_channel_square(
            keyword=keyword,
            page=page,
            page_size=page_size,
            login_user=login_user
        )
        return resp_200(data=result.model_dump())
    except Exception as e:
        logger.error(f"Failed to get channel square: {e}")
        return resp_500(message="Failed to get channel square")


@router.post("/subscribe")
async def subscribe_channel(
        req_param: SubscribeChannelRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Subscribe channel request API: Handles subscription requests based on channel type (public, private, approval required)."""
    status = await channel_service.subscribe_channel(req_param, login_user)
    return resp_200(data=status.value)


@router.post("/set_pin")
async def set_channel_pin(
        req_param: SetPinRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Set channel pin status."""
    await channel_service.set_channel_pin(req_param, login_user)
    return resp_200(data=True)


@router.get("/members")
async def list_channel_members(
        channel_id: str = Query(..., description='Channel ID'),
        page: int = Query(1, ge=1, description='Page number, default 1'),
        page_size: int = Query(20, ge=1, le=100, description='Page size, default 20'),
        keyword: str = Query(None, description='Username fuzzy search keyword'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Paginated query of channel member list, supports fuzzy search by username."""
    try:
        result = await channel_service.list_channel_members(
            channel_id=channel_id,
            page=page,
            page_size=page_size,
            keyword=keyword,
            login_user=login_user
        )
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"List members failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to list channel members: {e}")
        return resp_500(message="Failed to list channel members")


@router.post("/update_member_role")
async def update_member_role(
        req_param: UpdateMemberRoleRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Set member role (admin/member)."""

    await channel_service.update_member_role(req_param, login_user)
    return resp_200(data=True)


@router.post("/remove_member")
async def remove_member(
        req_param: RemoveMemberRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Remove channel member."""

    await channel_service.remove_member(req_param, login_user)
    return resp_200(data=True)


@router.get("/articles")
async def search_channel_articles(
        channel_id: str = Query(..., description='Channel ID'),
        keyword: Optional[str] = Query(None, description='Search keyword (title, content, publisher)'),
        source_ids: Optional[str] = Query(None, description='Specified source ID list, comma separated'),
        sub_channel_name: Optional[str] = Query(None, description='Sub-channel name'),
        page: int = Query(1, ge=1, description='Page number, default 1'),
        page_size: int = Query(20, ge=1, le=100, description='Page size, default 20'),
        only_unread: Optional[bool] = Query(False, description='Show unread only'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Paginated search of articles by channel, supports keyword search, source filtering, sub-channel filtering, results with highlighting."""
    try:
        # Parse comma-separated source ID list
        parsed_source_ids = None
        if source_ids:
            parsed_source_ids = [s.strip() for s in source_ids.split(',') if s.strip()]

        result = await channel_service.search_channel_articles(
            channel_id=channel_id,
            keyword=keyword,
            source_ids=parsed_source_ids,
            sub_channel_name=sub_channel_name,
            page=page,
            page_size=page_size,
            login_user=login_user,
            only_unread=only_unread,
        )
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"Search channel articles failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to search channel articles: {e}")
        return resp_500(message="Failed to search channel articles")


@router.get("/articles/detail/{article_id}")
async def get_article_detail(
        article_id: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Get article details by article ID and record read status."""
    try:
        result = await channel_service.get_article_detail(
            article_id=article_id,
            login_user=login_user,
        )
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"Get article detail failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to get article detail: {e}")
        return resp_500(message="Failed to get article detail")


@router.get("/{channel_id}")
async def get_channel_detail(
        channel_id: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Get channel details, including basic channel information, creator, subscriber count, article count, etc."""
    try:
        result = await channel_service.get_channel_detail(channel_id, login_user)
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"Get channel detail failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to get channel detail: {e}")
        return resp_500(message="Failed to get channel detail")


@router.put("/{channel_id}")
async def update_channel_info(
        channel_id: str,
        req_param: UpdateChannelRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Update channel information API"""
    try:
        result = await channel_service.update_channel(channel_id, req_param, login_user)
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"Update channel info failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to update channel: {e}")
        return resp_500(message="Failed to update channel")


@router.delete("/{channel_id}")
async def dismiss_channel(
        channel_id: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Dismiss channel API"""
    try:
        await channel_service.dismiss_channel(channel_id, login_user)
        return resp_200(data=True)
    except ValueError as e:
        logger.warning(f"Dismiss channel failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to dismiss channel: {e}")
        return resp_500(message="Failed to dismiss channel")


@router.post("/{channel_id}/unsubscribe")
async def unsubscribe_channel(
        channel_id: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Unsubscribe channel API"""
    try:
        await channel_service.unsubscribe_channel(channel_id, login_user)
        return resp_200(data=True)
    except ValueError as e:
        logger.warning(f"Unsubscribe channel failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to unsubscribe channel: {e}")
        return resp_500(message="Failed to unsubscribe channel")
