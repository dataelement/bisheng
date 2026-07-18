from time import perf_counter

from fastapi import APIRouter
from fastapi.params import Depends, Query
from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.chat.manager import ChatManager
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.flow import FlowStatus

router = APIRouter(tags=["Chat"])
chat_manager = ChatManager()


@router.get("/chat/online")
async def get_online_chat(
    *,
    keyword: str | None = None,
    tag_id: int | None = None,
    flow_type: int | None = None,
    page: int | None = 1,
    limit: int | None = 10,
    sort_by: str | None = None,
    search_description: bool | None = False,
    permission_id: str = Query(
        default="use_app",
        description="Fine-grained permission id for app list visibility",
    ),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Access to online workflows and assistants.

    sort_by:
        - None (default): apps with user conversations first (DESC by last-used), then by update_time DESC.
        - "update_time": pure update_time DESC — used by the admin recommended-apps picker.
    search_description:
        - False (default): keyword matches name only.
        - True: keyword matches name OR description.
    """
    total_start = perf_counter()
    if sort_by == "update_time":
        # F027: get_all_flows returns has_more instead of an exact total.
        data, _has_more = await WorkFlowService.get_all_flows(
            user,
            keyword,
            FlowStatus.ONLINE.value,
            tag_id,
            flow_type,
            page,
            limit,
            skip_pagination=False,
            search_description=bool(search_description),
            permission_id=permission_id,
        )
    else:
        flow_fetch_start = perf_counter()
        data = await WorkFlowService.get_online_flows_page(
            user,
            keyword,
            FlowStatus.ONLINE.value,
            tag_id,
            flow_type,
            page,
            limit,
            search_description=bool(search_description),
            permission_id=permission_id,
        )
        logger.info(
            "[perf][chat.online.flow_fetch] user_id={} flow_type={} keyword={} rows={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            keyword or "",
            len(data),
            (perf_counter() - flow_fetch_start) * 1000,
        )

    if sort_by == "update_time":
        # The default ranked path reuses its page permission map for can_share.
        enrich_can_share_start = perf_counter()
        data = await WorkFlowService.aenrich_apps_can_share(user, data)
        logger.info(
            "[perf][chat.online.can_share] user_id={} rows={} took_ms={:.2f}",
            user.user_id,
            len(data),
            (perf_counter() - enrich_can_share_start) * 1000,
        )

    logger.info(
        "[perf][chat.online.total] user_id={} flow_type={} sort_by={} page={} limit={} rows={} "
        "permission_id={} took_ms={:.2f}",
        user.user_id,
        flow_type,
        sort_by,
        page,
        limit,
        len(data),
        permission_id,
        (perf_counter() - total_start) * 1000,
    )
    return resp_200(data=data)
