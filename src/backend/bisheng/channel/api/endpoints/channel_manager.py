import logging

from fastapi import APIRouter, Depends, Query, Request

from bisheng.channel.api.dependencies import get_channel_authorization_service, get_channel_service
from bisheng.channel.domain.schemas.channel_authorization_schema import ChannelAuthorizeRequest
from bisheng.channel.domain.schemas.channel_manager_schema import (
    AddArticlesToKnowledgeSpaceRequest,
    AddInformationSourceRequest,
    CrawlWebsiteRequest,
    CreateChannelRequest,
    MyChannelQueryRequest,
    QueryTypeEnum,
    RemoveMemberRequest,
    SetPinRequest,
    SortByEnum,
    SubscribeChannelRequest,
    UpdateChannelRequest,
    UpdateMemberRoleRequest,
)
from bisheng.channel.domain.services.channel_authorization_service import ChannelAuthorizationService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.core.external.bisheng_information_client.client import BusinessType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manager", tags=["Channel Management"])


@router.post("/create")
async def create_channel(
    request: Request,
    req_param: CreateChannelRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Endpoint to create a new channel."""
    channel = await channel_service.create_channel(req_param, login_user, request)

    return resp_200(data=channel)


@router.get("/list_sources")
async def list_channel_information_sources(
    business_type: BusinessType = Query(..., description="Information source type: website / wechat"),
    page: int = Query(1, ge=1, description="Page number, default 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size, default 20"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to list information sources of a channel."""

    client = await get_bisheng_information_client()
    sources, total = await client.list_information_sources(business_type=business_type, page=page, page_size=page_size)
    return resp_200(data={"sources": [s.model_dump() for s in sources], "total": total})


@router.get("/search_sources")
async def search_channel_information_sources(
    keyword: str = Query(..., min_length=1, description="Search keyword, fuzzy match name and URL"),
    business_type: BusinessType | None = Query(None, description="Information source type: website / wechat"),
    page: int = Query(1, ge=1, description="Page number, default 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size, default 20"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Endpoint to search information sources of a channel by keyword."""
    client = await get_bisheng_information_client()
    sources, total = await client.search_information_sources(
        query=keyword, business_type=business_type, page=page, page_size=page_size
    )
    return resp_200(data={"sources": [s.model_dump() for s in sources], "total": total})


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
    query_type: QueryTypeEnum = Query(..., description="Query type: created / followed"),
    sort_by: SortByEnum = Query(SortByEnum.LATEST_UPDATE, description="Sort by, default latest update"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Endpoint to get channels related to the logged-in user, either created or followed, with sorting options."""
    query_data = MyChannelQueryRequest(query_type=query_type, sort_by=sort_by)
    result = await channel_service.get_my_channels(query_data, login_user)
    return resp_200(data=[item.model_dump() for item in result])


@router.get("/square")
async def get_channel_square(
    keyword: str | None = Query(None, description="Fuzzy search keyword (channel name/description)"),
    page: int = Query(1, ge=1, description="Page number, default 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size, default 20"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Channel square query: Paginated query of all released channels, supports fuzzy search, displays subscription status and subscriber count."""
    result = await channel_service.get_channel_square(
        keyword=keyword, page=page, page_size=page_size, login_user=login_user
    )
    return resp_200(data=result.model_dump())


@router.get("/recommend")
async def get_recommended_channels(
    limit: int = Query(12, ge=1, le=50, description="Max number of channels to return, default 12"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Home-page discovery recommendations: released PUBLIC channels sorted by article
    count descending, for the empty-state carousel. `total` is the qualifying public
    channel count so the client can fall back to the empty illustration when < 3."""
    result = await channel_service.get_recommended_channels(login_user=login_user, limit=limit)
    return resp_200(data=result.model_dump())


@router.post("/subscribe")
async def subscribe_channel(
    request: Request,
    req_param: SubscribeChannelRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Subscribe channel request API: Handles subscription requests based on channel type (public, private, approval required)."""
    status = await channel_service.subscribe_channel(req_param, login_user, request)
    return resp_200(data=status.value)


@router.post("/set_pin")
async def set_channel_pin(
    req_param: SetPinRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Set channel pin status."""
    await channel_service.set_channel_pin(req_param, login_user)
    return resp_200(data=True)


@router.get("/{channel_id}/permissions")
async def list_channel_permissions(
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.list_permissions(channel_id, login_user)
    return resp_200(data=[item.model_dump() for item in result])


@router.post("/{channel_id}/authorize")
async def authorize_channel(
    channel_id: str,
    req_param: ChannelAuthorizeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.authorize_channel(channel_id, req_param, login_user)
    return resp_200(data=result.model_dump())


@router.get("/{channel_id}/grantable-relation-models")
async def list_channel_grantable_relation_models(
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.grantable_relation_models(channel_id, login_user)
    return resp_200(data=[item.model_dump() for item in result])


@router.get("/{channel_id}/grant-subjects/users")
async def list_channel_grant_users(
    channel_id: str,
    keyword: str = Query("", description="User keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(2000, ge=1, le=5000, description="Page size"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.list_grant_users(channel_id, login_user, keyword, page, page_size)
    return resp_200(data=result)


# F038/T012: the eager full-tree ``GET /{channel_id}/grant-subjects/departments``
# was removed — the channel picker uses the lazy children/search/path-tree routes
# below so a large org tree never loads at once.


# F038: lazy channel department picker (browse one layer / search / locate).
@router.get("/{channel_id}/grant-subjects/departments/children")
async def list_channel_grant_departments_children(
    channel_id: str,
    parent_id: int | None = Query(None, description="None → root layer; else direct children of this internal id"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.list_grant_departments_children(channel_id, login_user, parent_id)
    return resp_200(data=result)


@router.get("/{channel_id}/grant-subjects/departments/search")
async def search_channel_grant_departments(
    channel_id: str,
    keyword: str = Query("", description="Department name keyword"),
    limit: int = Query(50, ge=1, le=200, description="Max matches"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.search_grant_departments(channel_id, login_user, keyword, limit)
    return resp_200(data=result)


@router.get("/{channel_id}/grant-subjects/departments/{dept_id:int}/path-tree")
async def get_channel_grant_departments_path_tree(
    channel_id: str,
    dept_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.get_grant_departments_path_tree(channel_id, login_user, dept_id)
    return resp_200(data=result)


@router.get("/{channel_id}/grant-subjects/user-groups")
async def list_channel_grant_user_groups(
    channel_id: str,
    keyword: str = Query("", description="User group keyword"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    authorization_service: ChannelAuthorizationService = Depends(get_channel_authorization_service),
):
    result = await authorization_service.list_grant_user_groups(channel_id, login_user, keyword)
    return resp_200(data=result)


@router.get("/members")
async def list_channel_members(
    channel_id: str = Query(..., description="Channel ID"),
    page: int = Query(1, ge=1, description="Page number, default 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size, default 20"),
    keyword: str = Query(None, description="Username fuzzy search keyword"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Paginated query of channel member list, supports fuzzy search by username."""
    result = await channel_service.list_channel_members(
        channel_id=channel_id, page=page, page_size=page_size, keyword=keyword, login_user=login_user
    )
    return resp_200(data=result.model_dump())


@router.post("/update_member_role")
async def update_member_role(
    req_param: UpdateMemberRoleRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Set member role (admin/member)."""

    await channel_service.update_member_role(req_param, login_user)
    return resp_200(data=True)


@router.post("/remove_member")
async def remove_member(
    req_param: RemoveMemberRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Remove channel member."""

    await channel_service.remove_member(req_param, login_user)
    return resp_200(data=True)


@router.get("/articles")
async def search_channel_articles(
    channel_id: str = Query(..., description="Channel ID"),
    keyword: str | None = Query(None, description="Search keyword (title, content, source ID)"),
    source_ids: str | None = Query(None, description="Specified source ID list, comma separated"),
    sub_channel_name: str | None = Query(None, description="Sub-channel name"),
    page: int = Query(1, ge=1, description="Page number, default 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size, default 20"),
    only_unread: bool | None = Query(False, description="Show unread only"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Paginated search of articles by channel, supports keyword search, source filtering, sub-channel filtering, results with highlighting."""
    # Parse comma-separated source ID list
    parsed_source_ids = None
    if source_ids:
        parsed_source_ids = [s.strip() for s in source_ids.split(",") if s.strip()]

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


@router.get("/articles/detail/{article_id}")
async def get_article_detail(
    article_id: str,
    channel_id: str = Query(..., description="Channel ID"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Get article details by article ID and record read status."""
    result = await channel_service.get_article_detail(
        article_id=article_id,
        channel_id=channel_id,
        login_user=login_user,
    )
    return resp_200(data=result.model_dump())


@router.get("/{channel_id}")
async def get_channel_detail(
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Get channel details, including basic channel information, creator, subscriber count, article count, etc."""
    result = await channel_service.get_channel_detail(channel_id, login_user)
    return resp_200(data=result.model_dump())


@router.get("/{channel_id}/unread-counts")
async def get_channel_unread_counts(
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """F040: per-sub-channel unread counts for the current user, split out of channel
    detail (the per-user ES cost no longer rides on the detail/preview path). The
    in-channel view fetches this lazily to fill sub-channel unread badges."""
    result = await channel_service.get_sub_channel_unread_counts(channel_id, login_user)
    return resp_200(data=result)


@router.put("/{channel_id}")
async def update_channel_info(
    channel_id: str,
    req_param: UpdateChannelRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Update channel information API"""
    result = await channel_service.update_channel(channel_id, req_param, login_user)
    return resp_200(data=result.model_dump())


@router.delete("/{channel_id}")
async def dismiss_channel(
    request: Request,
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Dismiss channel API"""
    await channel_service.dismiss_channel(channel_id, login_user, request)
    return resp_200(data=True)


@router.post("/{channel_id}/unsubscribe")
async def unsubscribe_channel(
    channel_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Unsubscribe channel API"""
    await channel_service.unsubscribe_channel(channel_id, login_user)
    return resp_200(data=True)


@router.post("/articles/add_to_knowledge_space")
async def add_articles_to_knowledge_space(
    req: AddArticlesToKnowledgeSpaceRequest,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    channel_service: "ChannelService" = Depends(get_channel_service),
):
    """Add channel articles to a knowledge space."""
    result = await channel_service.add_articles_to_knowledge_space(req, login_user, request)
    return resp_200(data=result)


# NOTE: Channel ➜ knowledge-space sync config (v2.5 Module D) is saved and
# returned as part of the Channel CRUD endpoints via the `knowledge_sync`
# field on CreateChannelRequest / UpdateChannelRequest / ChannelDetailResponse.
# Standalone /knowledge_sync endpoints were removed in favour of atomic
# create/update with the channel itself.
