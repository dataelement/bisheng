from fastapi import APIRouter, Body

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schemas import ChatList, FrequentlyUsedChat, UnifiedResponseModel, UsedAppPin, resp_200
from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.flow import AppInvalidCursorError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.workstation import AgentAlreadyExistsError, UsedAppNotFoundError, UsedAppNotOnlineError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user_link import UserLinkDao
from bisheng.permission.domain.services.application_permission_service import ApplicationPermissionService
from bisheng.permission.domain.workflow_app_permission import batch_user_may_share_app, object_type_for_flow_type
from bisheng.workstation.domain.services.constants import USED_APP_PIN_TYPE
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

    kwargs: dict = dict(id_list=app_ids, page=0, limit=0)
    if not login_user.is_admin():
        kwargs["status"] = FlowStatus.ONLINE.value
    data, _ = FlowDao.get_all_apps(**kwargs)
    data = await WorkFlowService.filter_apps_by_permission_id(login_user, data, "view_app")

    # Restore admin-configured order; unmatched items sort to the end.
    app_order = {app_id: idx for idx, app_id in enumerate(app_ids)}
    data.sort(key=lambda x: app_order.get(x["id"], len(app_ids)))

    data = WorkFlowService.add_extra_field(login_user, data)
    data = await WorkFlowService.aenrich_apps_can_share(login_user, data)
    return resp_200(data=data)


@router.get("/app/frequently_used")
async def get_frequently_used_chat(
    login_user=LoginUserDep,
    user_link_type: str | None = "app",
    page_size: int | None = 8,
    cursor: str | None = None,
):
    """List the user's favourite apps (F040/F027 pseudo-cursor envelope)."""
    result = await WorkFlowService.aget_frequently_used_flows_cursor(
        login_user,
        user_link_type,
        cursor=cursor,
        page_size=page_size,
    )
    return resp_200(data=result)


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
    page: int | None = 1,
    limit: int | None = 8,
    keyword: str | None = None,
):
    data, _ = await WorkFlowService.get_uncategorized_flows(login_user, page, limit, keyword)
    return resp_200(data=data)


@router.get("/app/used")
async def get_used_apps(login_user=LoginUserDep, page_size: int = 20, cursor: str | None = None):
    """List the apps the user has recently used (F040/F027 pseudo-cursor).

    The candidate set is the user's own used-app history (bounded per-user),
    ordered pinned-first then by last-used time — a custom order a keyset cursor
    over ``update_time`` can't express, so this uses the F027 AD-15 pseudo-cursor
    (key=``[page_num]``, **no total**, INV-6). The page is sliced BEFORE the
    tag / logo / can_share enrichment, so that per-page work is bounded by
    ``page_size`` instead of the whole history. Response shape:
    ``PageInfiniteCursorData`` (``{data, page_size, has_more, next_cursor}``).
    """
    context = "used_apps|sort=pinned_recency"
    try:
        decoded = decode_cursor(cursor, expected_key_len=1, expected_context=context)
    except CursorDecodeError as exc:
        raise AppInvalidCursorError(exception=exc)
    page_num = decoded[0] if decoded else 1
    if not isinstance(page_num, int) or page_num < 1:
        raise AppInvalidCursorError()

    flow_types = [FlowType.ASSISTANT.value, FlowType.WORKFLOW.value]
    used_apps = await MessageSessionDao.get_user_used_apps(user_id=login_user.user_id, flow_types=flow_types)
    if not used_apps:
        return resp_200(data=PageInfiniteCursorData(data=[], page_size=page_size, has_more=False, next_cursor=None))

    flow_ids = [app[0] for app in used_apps]
    last_used_time_map = {app[0]: app[1] for app in used_apps}
    pinned_links = UserLinkDao.get_user_link(login_user.user_id, [USED_APP_PIN_TYPE])
    pinned_flow_ids = {link.type_detail for link in pinned_links}

    apps, _ = await FlowDao.aget_all_apps(id_list=flow_ids, status=FlowStatus.ONLINE.value, page=0, limit=0)
    apps = await WorkFlowService.filter_apps_by_permission_id(login_user, apps, "view_app")

    def sort_key(app):
        app_id = app["id"]
        is_pinned = app_id in pinned_flow_ids
        used_time = last_used_time_map.get(app_id)
        return (not is_pinned, -used_time.timestamp() if used_time else 0)

    apps.sort(key=sort_key)

    # Pseudo-cursor slice (with +1 probe) BEFORE enrichment — only the page is
    # decorated with tags / logo / can_share.
    start_index = (page_num - 1) * page_size
    page_items = apps[start_index : start_index + page_size + 1]
    has_more = len(page_items) > page_size
    page_items = page_items[:page_size]

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

    share_pairs = []
    share_idx = []
    for idx, app in enumerate(result):
        ot = object_type_for_flow_type(int(app.get("flow_type") or 0))
        if ot:
            share_pairs.append((ot, str(app["id"])))
            share_idx.append(idx)
    if login_user.is_admin():
        for app in result:
            app["can_share"] = True
    elif share_pairs:
        flags = await batch_user_may_share_app(login_user, share_pairs)
        for j, app_i in enumerate(share_idx):
            result[app_i]["can_share"] = bool(flags[j])

    next_cursor = encode_cursor((page_num + 1,), context=context) if has_more else None
    return resp_200(
        data=PageInfiniteCursorData(
            data=result,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )
    )


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

    if not await ApplicationPermissionService.has_any_permission_async(
        login_user,
        object_type,
        str(flow_id),
        ["use_app"],
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
