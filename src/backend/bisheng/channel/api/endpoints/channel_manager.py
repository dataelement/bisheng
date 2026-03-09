import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.channel.api.dependencies import get_channel_service
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
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


@router.post("/add_website_source")
async def add_website_information_source(
        req_param: AddInformationSourceRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to add a new information source by URL."""
    try:
        client = await get_bisheng_information_client()
        result = await client.add_website_information_source(req_param.url)
        return resp_200(data=result.model_dump())
    except InformationSourceAddError as e:
        logger.error(f"Failed to add information source: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Unexpected error adding information source: {e}")
        return resp_500(message="Failed to add information source")


@router.post("/add_wechat_source")
async def add_wechat_information_source(
        req_param: AddInformationSourceRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to add a new WeChat information source by URL."""
    try:
        client = await get_bisheng_information_client()
        result = await client.add_wechat_information_source(req_param.url)
        return resp_200(data=result.model_dump())
    except InformationSourceAddError as e:
        logger.error(f"Failed to add WeChat information source: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Unexpected error adding WeChat information source: {e}")
        return resp_500(message="Failed to add WeChat information source")


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


@router.get("/my_channels")
async def get_my_channels(
        query_type: QueryTypeEnum = Query(..., description='查询类型：created(我创建的) / followed(我关注的)'),
        sort_by: SortByEnum = Query(SortByEnum.LATEST_UPDATE, description='排序方式，默认最近更新'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Endpoint to get channels related to the logged-in user, either created or followed, with sorting options."""
    try:
        query_data = MyChannelQueryRequest(query_type=query_type, sort_by=sort_by)
        result = await channel_service.get_my_channels(query_data, login_user)
        return resp_200(data=[item.model_dump() for item in result])
    except Exception as e:
        logger.error(f"Failed to get my channels: {e}")
        return resp_500(message="Failed to get my channels")


@router.get("/square")
async def get_channel_square(
        keyword: Optional[str] = Query(None, description='模糊搜索关键词（频道名称/简介）'),
        page: int = Query(1, ge=1, description='页码，默认1'),
        page_size: int = Query(20, ge=1, le=100, description='每页数量，默认20'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """频道广场查询：分页查询所有已发布频道，支持模糊搜索，展示订阅状态和订阅人数。"""
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
    """订阅频道申请接口：根据频道类型（公开、私密、需要审批）处理订阅申请。"""
    try:
        status = await channel_service.subscribe_channel(req_param, login_user)
        return resp_200(data=status.value)
    except ValueError as e:
        logger.warning(f"Subscribe channel failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to subscribe to channel: {e}")
        return resp_500(message="Failed to subscribe to channel")


@router.post("/set_pin")
async def set_channel_pin(
        req_param: SetPinRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """设置频道置顶状态。"""
    try:
        await channel_service.set_channel_pin(req_param, login_user)
        return resp_200(data=True)
    except ValueError as e:
        logger.warning(f"Set pin failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to set channel pin: {e}")
        return resp_500(message="Failed to set channel pin")


@router.get("/members")
async def list_channel_members(
        channel_id: str = Query(..., description='频道 ID'),
        page: int = Query(1, ge=1, description='页码，默认1'),
        page_size: int = Query(20, ge=1, le=100, description='每页数量，默认20'),
        keyword: str = Query(None, description='用户名模糊搜索关键词'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """分页查询频道成员列表，支持按用户名模糊搜索。"""
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
    """设置成员角色（管理员/普通成员）。"""
    try:
        await channel_service.update_member_role(req_param, login_user)
        return resp_200(data=True)
    except ValueError as e:
        logger.warning(f"Update member role failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to update member role: {e}")
        return resp_500(message="Failed to update member role")


@router.post("/remove_member")
async def remove_member(
        req_param: RemoveMemberRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """移除频道成员。"""
    try:
        await channel_service.remove_member(req_param, login_user)
        return resp_200(data=True)
    except ValueError as e:
        logger.warning(f"Remove member failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to remove member: {e}")
        return resp_500(message="Failed to remove member")


@router.get("/articles")
async def search_channel_articles(
        channel_id: str = Query(..., description='频道 ID'),
        keyword: Optional[str] = Query(None, description='搜索关键词（标题、正文、发布者）'),
        source_ids: Optional[str] = Query(None, description='指定信源ID列表，逗号分隔'),
        sub_channel_name: Optional[str] = Query(None, description='子频道名称'),
        page: int = Query(1, ge=1, description='页码，默认1'),
        page_size: int = Query(20, ge=1, le=100, description='每页数量，默认20'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """根据频道分页检索文章，支持关键词搜索、信源过滤、子频道过滤，结果高亮显示。"""
    try:
        # 解析逗号分隔的信源ID列表
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
        )
        return resp_200(data=result.model_dump())
    except ValueError as e:
        logger.warning(f"Search channel articles failed: {e}")
        return resp_500(message=str(e))
    except Exception as e:
        logger.error(f"Failed to search channel articles: {e}")
        return resp_500(message="Failed to search channel articles")
