import asyncio
import json
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body
from fastapi.middleware.wsgi import WSGIMiddleware

a = WSGIMiddleware

from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.v1.schemas import ChatInput, resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.open_endpoints.domain.schemas.message import SyncMessage

router = APIRouter(prefix='/chat', tags=['OpenAPI', 'Chat'])


@router.post('/gen_title')
async def gen_title_v2(conversationId: str = Body(..., embed=True)):
    """Get conversation title without authentication (v2 open endpoint)."""
    await asyncio.sleep(5)
    messages = await MessageSessionDao.async_get_one(conversationId)
    return resp_200(data={'title': messages.name if messages else 'New Chat'})


@router.get('/history')
async def get_chat_history_v2(*,
                              chat_id: str,
                              flow_id: str,
                              id: Optional[str] = None,
                              page_size: Optional[int] = 20):
    """Get chat history without authentication (v2 open endpoint)."""
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)
    return resp_200(history)


# @router.get('/source')
# async def query_source(message_id: int, session: Session = Depends(get_session)):
#     """source of message_id"""
#     db_recall = session.query(RecallChunk).where(RecallChunk.message_id == message_id).all()


@router.post('/liked', status_code=200)
def like_response(*, data: dict):
    message_id = data.get('message_id')
    liked = data.get('liked')
    with get_sync_db_session() as session:
        message = session.get(ChatMessage, message_id)
        message.liked = liked
        session.add(message)
        session.commit()
    return {'status_code': 200, 'status_message': 'success'}


@router.post('/solved', status_code=200)
def solve_response(*, data: dict):
    chat_id = data.get('chat_id')
    solved = data.get('solved')
    with get_sync_db_session() as session:
        messages = session.query(ChatMessage).where(ChatMessage.chat_id == chat_id).all()
    for message in messages:
        message.solved = solved
    with get_sync_db_session() as session:
        session.add(message)
        session.commit()
    return {'status_code': 200, 'status_message': 'success'}


@router.post('/comment', status_code=200)
def comment(*, data: ChatInput):
    comment_answer(data.message_id, data.comment)
    return resp_200()


@router.post('/sync/messages', status_code=200)
def sync_message(*,
                 flow_id: UUID = Body(embed=True),
                 chat_id: str = Body(embed=True),
                 message_list: List[SyncMessage] = Body(embed=True),
                 user_id: int = Body(default=None, embed=True)):
    flow_id = flow_id.hex
    user_id = user_id if user_id else settings.get_from_db('default_operator').get('user')

    batch_message = [
        ChatMessage(is_bot=message.is_send,
                    source=0,
                    message=message.message,
                    extra=json.dumps(message.extra),
                    type='answer',
                    category='answer',
                    flow_id=flow_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    create_time=message.create_time) for message in message_list
    ]
    ChatMessageDao.insert_batch(batch_message)
    return resp_200()
