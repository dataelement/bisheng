import asyncio
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.params import Depends

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
                          user: UserPayload = Depends(UserPayload.get_login_user)):
    """Access to online workflows and assistants."""
    data, total = await asyncio.to_thread(
        WorkFlowService.get_all_flows,
        user, keyword, FlowStatus.ONLINE.value, tag_id, flow_type, page, limit,
        skip_pagination=True)

    # Get user's last conversation time per app
    used_apps = await MessageSessionDao.get_user_used_apps(use_create_time=True)
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

    return resp_200(data=data)
