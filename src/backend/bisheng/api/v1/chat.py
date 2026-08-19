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
    limit: int | None = 10,
    cursor: str | None = None,
    sort_by: str | None = None,
    search_description: bool | None = False,
    action: str = Query(
        default="use",
        pattern="^(visible|use)$",
        description="Concrete action required for each app",
    ),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Access to online workflows and assistants (F027 cursor waterfall).

    Response shape (PageInfiniteCursorData): ``{data, page_size, has_more, next_cursor}``.
    Pass the previous response's ``next_cursor`` as ``cursor``; omit (or empty) for the
    first page. ``limit`` is the page size. The legacy ``page`` is gone — combining
    ReBAC filtering with offset paging re-scanned every prior page on deep pages.

    sort_by:
        - None (default): apps with user conversations first (DESC by last-used), then update_time DESC.
        - "update_time": pure update_time DESC — used by the admin recommended-apps picker.
    search_description:
        - False (default): keyword matches name only.
        - True: keyword matches name OR description.
    """
    total_start = perf_counter()
    page_size = limit or 10
    if sort_by == "update_time":
        result = await WorkFlowService.get_all_flows_envelope(
            user,
            keyword,
            FlowStatus.ONLINE.value,
            tag_id,
            flow_type,
            cursor=cursor,
            page_size=page_size,
            search_description=bool(search_description),
            action=action,
        )
        # get_all_flows_envelope resolves edit (write) but not share; decorate
        # the page (bounded by page_size) with can_share.
        await WorkFlowService.aenrich_apps_can_share(user, result.data)
    else:
        result = await WorkFlowService.get_online_flows_cursor(
            user,
            keyword,
            FlowStatus.ONLINE.value,
            tag_id,
            flow_type,
            cursor=cursor,
            page_size=page_size,
            search_description=bool(search_description),
            action=action,
        )

    logger.info(
        "[perf][chat.online.total] user_id={} flow_type={} sort_by={} limit={} rows={} "
        "action={} has_more={} took_ms={:.2f}",
        user.user_id,
        flow_type,
        sort_by,
        page_size,
        len(result.data),
        action,
        result.has_more,
        (perf_counter() - total_start) * 1000,
    )
    return resp_200(data=result)
