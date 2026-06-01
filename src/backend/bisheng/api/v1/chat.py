from time import perf_counter
from typing import Optional

from fastapi import APIRouter
from fastapi.params import Depends, Query
from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.chat.manager import ChatManager
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.flow import FlowStatus
from bisheng.database.models.session import MessageSessionDao

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()


@router.get('/chat/online')
async def get_online_chat(*,
                          keyword: Optional[str] = None,
                          tag_id: Optional[int] = None,
                          flow_type: Optional[int] = None,
                          page: Optional[int] = 1,
                          limit: Optional[int] = 10,
                          sort_by: Optional[str] = None,
                          search_description: Optional[bool] = False,
                          permission_id: str = Query(
                              default='use_app',
                              description='Fine-grained permission id for app list visibility',
                          ),
                          user: UserPayload = Depends(UserPayload.get_login_user)):
    """Access to online workflows and assistants.

    sort_by:
        - None (default): apps with user conversations first (DESC by last-used), then by update_time DESC.
        - "update_time": pure update_time DESC — used by the admin recommended-apps picker.
    search_description:
        - False (default): keyword matches name only.
        - True: keyword matches name OR description.
    """
    total_start = perf_counter()
    if sort_by == 'update_time':
        # F027: get_all_flows now returns (data, has_more); ``total`` was removed.
        # This chat endpoint logs are the only consumers; we log ``has_more``.
        data, has_more = await WorkFlowService.get_all_flows(
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
        total = len(data)  # local view; not authoritative across DB
    else:
        flow_fetch_start = perf_counter()
        data, has_more = await WorkFlowService.get_all_flows(
            user,
            keyword,
            FlowStatus.ONLINE.value,
            tag_id,
            flow_type,
            page,
            limit,
            skip_pagination=True,
            search_description=bool(search_description),
            permission_id=permission_id,
        )
        logger.info(
            '[perf][chat.online.flow_fetch] user_id={} flow_type={} keyword={} rows={} has_more={} took_ms={:.2f}',
            user.user_id,
            flow_type,
            keyword or '',
            len(data),
            has_more,
            (perf_counter() - flow_fetch_start) * 1000,
        )

        # Get user's last conversation time per app
        flow_types = [flow_type] if flow_type is not None else None
        used_apps_start = perf_counter()
        used_apps = await MessageSessionDao.get_user_used_apps(
            user_id=user.user_id,
            flow_types=flow_types,
            use_create_time=True,
        )
        logger.info(
            '[perf][chat.online.used_apps] user_id={} flow_type={} used_apps={} took_ms={:.2f}',
            user.user_id,
            flow_type,
            len(used_apps),
            (perf_counter() - used_apps_start) * 1000,
        )
        used_map = {app[0]: app[1] for app in used_apps}

        # Sort: apps with conversations first (by last used time DESC),
        #       then apps without (by update_time DESC)
        def sort_key(app):
            last_chat = used_map.get(app['id'])
            if last_chat:
                return (0, -last_chat.timestamp())
            return (1, -app['update_time'].timestamp() if app.get('update_time') else 0)

        data.sort(key=sort_key)

        # Manual pagination
        total = len(data)
        start_index = (page - 1) * limit
        end_index = start_index + limit
        data = data[start_index:end_index]

    logger.info(
        '[perf][chat.online.total] user_id={} flow_type={} sort_by={} page={} limit={} total={} rows={} '
        'permission_id={} took_ms={:.2f}',
        user.user_id,
        flow_type,
        sort_by,
        page,
        limit,
        total,
        len(data),
        permission_id,
        (perf_counter() - total_start) * 1000,
    )
    return resp_200(data=data)
