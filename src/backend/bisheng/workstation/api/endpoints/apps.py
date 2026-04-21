from typing import Optional

from fastapi import APIRouter, Body

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schemas import ChatList, FrequentlyUsedChat, UnifiedResponseModel, UsedAppPin, resp_200
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.workstation import AgentAlreadyExistsError, UsedAppNotFoundError, UsedAppNotOnlineError
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user_link import UserLinkDao

from ..dependencies import LoginUserDep
from ...domain.services.workstation_service import WorkStationService
from ...domain.services.constants import USED_APP_PIN_TYPE

router = APIRouter()


@router.get('/app/recommended')
def get_recommended_apps(login_user=LoginUserDep):
    """Return admin-configured recommended apps.

    - Admins (config page): return every configured app so the selection can echo
      even if an app later went offline.
    - Regular users (chat landing): filter to online apps the user can access.
    """
    config = WorkStationService.get_config()
    if not config or not config.recommendedApps:
        return resp_200(data=[])

    app_ids = config.recommendedApps

    kwargs: dict = dict(id_list=app_ids, page=0, limit=0)
    if not login_user.is_admin():
        kwargs['status'] = FlowStatus.ONLINE.value
        kwargs['user_id'] = login_user.user_id
        kwargs['id_extra'] = login_user.get_user_access_resource_ids(
            [AccessType.FLOW, AccessType.WORKFLOW, AccessType.ASSISTANT_READ]
        )
    data, _ = FlowDao.get_all_apps(**kwargs)

    # Restore admin-configured order; unmatched items sort to the end.
    app_order = {app_id: idx for idx, app_id in enumerate(app_ids)}
    data.sort(key=lambda x: app_order.get(x['id'], len(app_ids)))

    data = WorkFlowService.add_extra_field(login_user, data)
    return resp_200(data=data)


@router.get('/app/frequently_used')
def get_frequently_used_chat(
    login_user=LoginUserDep,
    user_link_type: Optional[str] = 'app',
    page: Optional[int] = 1,
    limit: Optional[int] = 8,
):
    data, _ = WorkFlowService.get_frequently_used_flows(login_user, user_link_type, page, limit)
    return resp_200(data=data)


@router.post('/app/frequently_used')
def add_frequently_used_chat(login_user=LoginUserDep, data: FrequentlyUsedChat = Body(...)):
    is_new = WorkFlowService.add_frequently_used_flows(login_user, data.user_link_type, data.type_detail)
    if is_new:
        return resp_200(message='Added')
    return AgentAlreadyExistsError.return_resp()


@router.delete('/app/frequently_used')
def delete_frequently_used_chat(
    login_user=LoginUserDep,
    user_link_type: Optional[str] = None,
    type_detail: Optional[str] = None,
):
    WorkFlowService.delete_frequently_used_flows(login_user, user_link_type, type_detail)
    return resp_200(message='Delete successful')


@router.get('/app/uncategorized')
def get_uncategorized_chat(
    login_user=LoginUserDep,
    page: Optional[int] = 1,
    limit: Optional[int] = 8,
    keyword: Optional[str] = None,
):
    data, _ = WorkFlowService.get_uncategorized_flows(login_user, page, limit, keyword)
    return resp_200(data=data)


@router.get('/app/used')
async def get_used_apps(login_user=LoginUserDep, page: int = 1, limit: int = 20):
    flow_types = [FlowType.ASSISTANT.value, FlowType.WORKFLOW.value]
    used_apps = await MessageSessionDao.get_user_used_apps(user_id=login_user.user_id, flow_types=flow_types)
    if not used_apps:
        return resp_200(data={'list': [], 'total': 0})

    flow_ids = [app[0] for app in used_apps]
    last_used_time_map = {app[0]: app[1] for app in used_apps}
    pinned_links = UserLinkDao.get_user_link(login_user.user_id, [USED_APP_PIN_TYPE])
    pinned_flow_ids = {link.type_detail for link in pinned_links}

    if login_user.is_admin():
        apps, _ = await FlowDao.aget_all_apps(id_list=flow_ids, status=FlowStatus.ONLINE.value, page=0, limit=0)
    else:
        id_extra = login_user.get_merged_rebac_app_resource_ids(for_write=False)
        apps, _ = await FlowDao.aget_all_apps(
            id_list=flow_ids,
            status=FlowStatus.ONLINE.value,
            user_id=login_user.user_id,
            id_extra=id_extra,
            page=0,
            limit=0,
        )

    def sort_key(app):
        app_id = app['id']
        is_pinned = app_id in pinned_flow_ids
        used_time = last_used_time_map.get(app_id)
        return (not is_pinned, -used_time.timestamp() if used_time else 0)

    apps.sort(key=sort_key)
    resource_tag_dict = TagDao.get_tags_by_resource(None, flow_ids)
    result = []
    for app in apps:
        app_id = app['id']
        app['is_pinned'] = app_id in pinned_flow_ids
        app['last_used_time'] = last_used_time_map.get(app_id)
        app['logo'] = WorkFlowService.get_logo_share_link(app.get('logo'))
        app['tags'] = resource_tag_dict.get(app_id, [])
        result.append(app)

    total = len(result)
    start_index = (page - 1) * limit
    end_index = start_index + limit
    return resp_200(data={'list': result[start_index:end_index], 'total': total})


@router.post('/app/used/pin')
async def pin_used_app(login_user=LoginUserDep, data: UsedAppPin = Body(..., description='App to pin')):
    flow_id = data.flow_id
    app_info = await FlowDao.aget_flow_by_id(flow_id)
    if not app_info:
        raise UsedAppNotFoundError(flow_id=flow_id)
    if app_info.status != FlowStatus.ONLINE.value:
        raise UsedAppNotOnlineError(flow_id=flow_id)

    if app_info.flow_type == FlowType.ASSISTANT.value:
        access_type = AccessType.ASSISTANT_READ
    elif app_info.flow_type == FlowType.WORKFLOW.value:
        access_type = AccessType.WORKFLOW
    else:
        raise UsedAppNotFoundError(flow_id=flow_id)

    if not await login_user.async_access_check(app_info.user_id, flow_id, access_type):
        return UnAuthorizedError.return_resp()

    _, is_new = UserLinkDao.add_user_link(
        user_id=login_user.user_id,
        type=USED_APP_PIN_TYPE,
        type_detail=flow_id,
    )
    if is_new:
        return resp_200(message='Pinned successfully')
    return resp_200(message='Already pinned')


@router.delete('/app/used/pin')
async def unpin_used_app(login_user=LoginUserDep, flow_id: str = Body(..., embed=True)):
    UserLinkDao.delete_user_link(user_id=login_user.user_id, type=USED_APP_PIN_TYPE, type_detail=flow_id)
    return resp_200(message='Unpinned successfully')


@router.get('/app/conversations', summary='Get conversations for a specific app', response_model=UnifiedResponseModel)
async def get_app_conversations(flow_id: str, page: int = 1, limit: int = 10, login_user=LoginUserDep):
    sessions = await MessageSessionDao.afilter_session(
        flow_ids=[flow_id],
        user_ids=[login_user.user_id],
        page=page,
        limit=limit,
        include_delete=False,
    )
    if not sessions:
        return resp_200(data={'list': [], 'total': 0})

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
            logo=WorkFlowService.get_logo_share_link(one.flow_logo) if one.flow_logo else '',
            latest_message=latest_messages.get(one.chat_id, None),
            create_time=one.create_time,
            update_time=one.update_time,
        )
        for one in sessions
    ]
    return resp_200(data={'list': result, 'total': total})
