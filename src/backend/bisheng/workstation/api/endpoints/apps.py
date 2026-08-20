from fastapi import APIRouter, Body

from bisheng.api.services.workflow import CHAT_ENTRY_EXCLUDED_FLOW_TYPES, WorkFlowService
from bisheng.api.v1.schemas import ChatList, FrequentlyUsedChat, UnifiedResponseModel, UsedAppPin, resp_200
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.workstation import AgentAlreadyExistsError, UsedAppNotFoundError, UsedAppNotOnlineError
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user_link import UserLinkDao
from bisheng.permission.application.business_authorization import (
    check_business_action,
)
from bisheng.workstation.domain.services.constants import USED_APP_PIN_TYPE, USED_APP_RECENT_TYPE
from bisheng.workstation.domain.services.workstation_service import WorkStationService

from ..dependencies import LoginUserDep

router = APIRouter()


@router.get("/app/recommended")
async def get_recommended_apps(login_user=LoginUserDep):
    """Return admin-configured recommended apps.

    - Admins (config page): return every configured app so the selection can echo
      even if an app later went offline.
    - Regular users (chat landing): filter to online apps the user can access.
    """
    config = await WorkStationService.aget_config()
    if not config or not config.recommendedApps:
        return resp_200(data=[])

    app_ids = config.recommendedApps

    kwargs: dict = {"id_list": app_ids, "page": 0, "limit": 0}
    if not login_user.is_admin():
        kwargs["status"] = FlowStatus.ONLINE.value
    data, _ = FlowDao.get_all_apps(**kwargs)
    # An administrator may configure any application id here, hosted ones
    # included; a recommendation card opens the conversation page, which a
    # hosted application does not have.
    data = await WorkFlowService.filter_apps_by_action(
        login_user,
        data,
        "visible",
        exclude_flow_types=CHAT_ENTRY_EXCLUDED_FLOW_TYPES,
    )

    # Restore admin-configured order; unmatched items sort to the end.
    app_order = {app_id: idx for idx, app_id in enumerate(app_ids)}
    data.sort(key=lambda x: app_order.get(x["id"], len(app_ids)))

    writeable_ids = await WorkFlowService.aget_writeable_app_ids(login_user, data)
    data = WorkFlowService.add_extra_field(login_user, data, writeable_ids=writeable_ids)
    data = await WorkFlowService.aenrich_apps_can_share(login_user, data)
    return resp_200(data=data)


@router.get("/app/frequently_used")
async def get_frequently_used_chat(
    login_user=LoginUserDep,
    user_link_type: str | None = "app",
    page: int | None = 1,
    limit: int | None = 8,
):
    data, _ = await WorkFlowService.get_frequently_used_flows(login_user, user_link_type, page, limit)
    return resp_200(data=data)


@router.post("/app/frequently_used")
def add_frequently_used_chat(login_user=LoginUserDep, data: FrequentlyUsedChat = Body(...)):
    is_new = WorkFlowService.add_frequently_used_flows(login_user, data.user_link_type, data.type_detail)
    if is_new:
        return resp_200(message="Added")
    return AgentAlreadyExistsError.return_resp()


@router.delete("/app/frequently_used")
def delete_frequently_used_chat(
    login_user=LoginUserDep,
    user_link_type: str | None = None,
    type_detail: str | None = None,
):
    WorkFlowService.delete_frequently_used_flows(login_user, user_link_type, type_detail)
    return resp_200(message="Delete successful")


@router.get("/app/uncategorized")
async def get_uncategorized_chat(
    login_user=LoginUserDep,
    limit: int | None = 8,
    keyword: str | None = None,
    cursor: str | None = None,
):
    """Untagged online apps (F027 cursor waterfall).

    Response shape (PageInfiniteCursorData): ``{data, page_size, has_more, next_cursor}``.
    Pass the previous response's ``next_cursor`` as ``cursor``; omit (or empty) for the
    first page. ``limit`` is the page size. The legacy ``page`` / ``total`` are gone —
    deep offset pages re-scanned and re-permission-checked every prior page.
    """
    data = await WorkFlowService.get_uncategorized_flows_envelope(
        login_user,
        cursor=cursor,
        page_size=limit or 8,
        keyword=keyword,
    )
    return resp_200(data=data)


@router.get("/app/used")
async def get_used_apps(login_user=LoginUserDep, page: int = 1, limit: int = 20):
    """List the apps the user has recently used (pinned-first, then by last-used).

    The candidate set is the user's own used-app history — bounded per-user, so it
    stays on the offset ``{list, total}`` contract (INV-6 exemption: per-user
    bounded, no deep pagination). F040 keeps the enrich-AFTER-paginate win though:
    the page is sliced first and only then decorated with tags / logo / can_share,
    so that per-request enrichment is bounded by ``limit`` rather than the whole
    history (the previous code enriched every used app before slicing).
    """
    flow_types = [FlowType.ASSISTANT.value, FlowType.WORKFLOW.value]
    used_apps = await MessageSessionDao.get_user_used_apps(user_id=login_user.user_id, flow_types=flow_types)
    last_used_time_map = {app[0]: app[1] for app in used_apps}
    # Hosted applications have no MessageSession (they are not conversational), so
    # their "recently used" is recorded explicitly on entry via UserLink
    # (USED_APP_RECENT_TYPE). Merge that history in so a hosted app the user has
    # opened shows up here alongside chatted-with workflows / assistants.
    recent_hosted_links = UserLinkDao.get_user_link(login_user.user_id, [USED_APP_RECENT_TYPE])
    for link in recent_hosted_links:
        last_used_time_map[link.type_detail] = link.update_time or link.create_time
    if not last_used_time_map:
        return resp_200(data={"list": [], "total": 0})

    flow_ids = list(last_used_time_map.keys())
    pinned_links = UserLinkDao.get_user_link(login_user.user_id, [USED_APP_PIN_TYPE])
    pinned_flow_ids = {link.type_detail for link in pinned_links}

    apps, _ = await FlowDao.aget_all_apps(id_list=flow_ids, status=FlowStatus.ONLINE.value, page=0, limit=0)
    # No type exclusion here: now that hosted-app usage is tracked, a hosted app is
    # a legitimate "recently used" entry; the recorded candidate set above is what
    # bounds the list. ``filter_apps_by_action`` still drops anything the user may
    # no longer see (action="visible" routes flow_type=35 to the F048 app adapter).
    apps = await WorkFlowService.filter_apps_by_action(
        login_user,
        apps,
        "visible",
    )

    def sort_key(app):
        app_id = app["id"]
        is_pinned = app_id in pinned_flow_ids
        used_time = last_used_time_map.get(app_id)
        return (not is_pinned, -used_time.timestamp() if used_time else 0)

    apps.sort(key=sort_key)

    total = len(apps)
    # Slice BEFORE enrichment so tags / logo / can_share only decorate the page.
    start_index = (page - 1) * limit
    page_items = apps[start_index : start_index + limit]

    # Hosted-app rows carry no ``slug`` from the union; fill it (same enrichment the
    # app square uses) so the client can re-enter ``/apps/{slug}`` from "recently
    # used" instead of falling through to the conversation route they have none of.
    await WorkFlowService._attach_hosted_app_entry_fields(page_items)

    page_flow_ids = [app["id"] for app in page_items]
    resource_tag_dict = TagDao.get_tags_by_resource(None, page_flow_ids)
    result = []
    for app in page_items:
        app_id = app["id"]
        app["is_pinned"] = app_id in pinned_flow_ids
        app["last_used_time"] = last_used_time_map.get(app_id)
        app["logo"] = WorkFlowService.get_logo_share_link(app.get("logo"))
        app["tags"] = resource_tag_dict.get(app_id, [])
        app["can_share"] = False
        result.append(app)

    await WorkFlowService.aenrich_apps_can_share(login_user, result)

    return resp_200(data={"list": result, "total": total})


@router.post("/app/used/record")
async def record_used_app(
    login_user=LoginUserDep, data: UsedAppPin = Body(..., description="Hosted app the user just opened")
):
    """Record that the user opened a hosted application, for the "recently used" list.

    Conversational apps (workflow / assistant) land in "recently used" through their
    MessageSession; hosted applications have none, so the client posts the open here
    when entering ``/apps/{slug}``. Idempotent per (user, app): the row's
    ``update_time`` is bumped so the most recent open sorts first.

    Authorization is delegated to ``check_business_action`` for resource_type
    ``app``: a non-existent, cross-tenant, or not-permitted app is refused here
    without leaking whether it exists (AC-29), so no separate existence check is
    needed. Only hosted apps are addressed as ``app``; workflows/assistants would
    resolve under their own types and are not the concern of this endpoint.
    """
    flow_id = data.flow_id
    if not await check_business_action(login_user, resource_type="app", resource_id=flow_id, action="use"):
        return UnAuthorizedError.return_resp()
    UserLinkDao.touch_user_link(user_id=login_user.user_id, type=USED_APP_RECENT_TYPE, type_detail=flow_id)
    return resp_200(message="Recorded")


@router.post("/app/used/pin")
async def pin_used_app(login_user=LoginUserDep, data: UsedAppPin = Body(..., description="App to pin")):
    flow_id = data.flow_id
    app_info = await FlowDao.aget_flow_by_id(flow_id)
    if not app_info:
        raise UsedAppNotFoundError(flow_id=flow_id)
    if app_info.status != FlowStatus.ONLINE.value:
        raise UsedAppNotOnlineError(flow_id=flow_id)

    if app_info.flow_type == FlowType.ASSISTANT.value:
        object_type = "assistant"
    elif app_info.flow_type == FlowType.WORKFLOW.value:
        object_type = "workflow"
    else:
        raise UsedAppNotFoundError(flow_id=flow_id)

    if not await check_business_action(
        login_user,
        resource_type=object_type,
        resource_id=flow_id,
        action="use",
    ):
        return UnAuthorizedError.return_resp()

    _, is_new = UserLinkDao.add_user_link(
        user_id=login_user.user_id,
        type=USED_APP_PIN_TYPE,
        type_detail=flow_id,
    )
    if is_new:
        return resp_200(message="Pinned successfully")
    return resp_200(message="Already pinned")


@router.delete("/app/used/pin")
async def unpin_used_app(login_user=LoginUserDep, flow_id: str = Body(..., embed=True)):
    UserLinkDao.delete_user_link(user_id=login_user.user_id, type=USED_APP_PIN_TYPE, type_detail=flow_id)
    return resp_200(message="Unpinned successfully")


@router.get("/app/conversations", summary="Get conversations for a specific app", response_model=UnifiedResponseModel)
async def get_app_conversations(flow_id: str, page: int = 1, limit: int = 10, login_user=LoginUserDep):
    sessions = await MessageSessionDao.afilter_session(
        flow_ids=[flow_id],
        user_ids=[login_user.user_id],
        page=page,
        limit=limit,
        include_delete=False,
    )
    if not sessions:
        return resp_200(data={"list": [], "total": 0})

    total = await MessageSessionDao.filter_session_count(
        flow_ids=[flow_id],
        user_ids=[login_user.user_id],
        include_delete=False,
    )
    chat_ids = [one.chat_id for one in sessions]
    latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(chat_ids)
    latest_messages = {one.chat_id: one for one in latest_messages}
    result = [
        ChatList(
            name=one.name,
            chat_id=one.chat_id,
            flow_id=one.flow_id,
            flow_name=one.flow_name,
            flow_type=one.flow_type,
            logo=WorkFlowService.get_logo_share_link(one.flow_logo) if one.flow_logo else "",
            latest_message=latest_messages.get(one.chat_id, None),
            create_time=one.create_time,
            update_time=one.update_time,
        )
        for one in sessions
    ]
    return resp_200(data={"list": result, "total": total})
