from typing import Optional

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload, get_login_user
from bisheng.common.schemas.api import resp_200
from ..domain.chat import ChatSessionService

router = APIRouter(prefix='/session', tags=['Chat Session'])


@router.get('/chat/history')
async def get_chat_message_public(*,
                                  chat_id: str,
                                  flow_id: str,
                                  id: Optional[str] = None,
                                  page_size: Optional[int] = 20,
                                  login_user: UserPayload = Depends(get_login_user)):
    """ api for audit module and mark qa """
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)
    return resp_200(data=history)
