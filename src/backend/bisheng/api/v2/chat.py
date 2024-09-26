import json
from typing import List, Optional
from uuid import UUID, uuid4

from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.services.utils import set_flow_knowledge_id
from bisheng.api.v1.schemas import ChatInput, resp_200
from bisheng.api.v2.schema.message import SyncMessage
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.processing.process import process_tweaks
from bisheng.settings import settings
from bisheng.utils.logger import logger
from fastapi import APIRouter, Body, WebSocket, status

router = APIRouter(prefix='/chat', tags=['OpenAPI', 'Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期


@router.websocket('/ws/{flow_id}')
async def union_websocket(flow_id: str,
                          websocket: WebSocket,
                          chat_id: Optional[str] = None,
                          tweak: Optional[str] = None,
                          knowledge_id: Optional[int] = None):
    """Websocket endpoint forF  chat."""
    if chat_id:
        with session_getter() as session:
            db_flow = session.get(Flow, flow_id)
        if not db_flow:
            await websocket.accept()
            message = '该技能已被删除'
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
        if db_flow.status != 2:
            await websocket.accept()
            message = '当前技能未上线，无法直接对话'
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
        graph_data = db_flow.data

    try:
        if tweak:
            tweak = json.loads(tweak)
            graph_data = process_tweaks(graph_data, tweak)
        # vectordatabase update
        if knowledge_id:
            set_flow_knowledge_id(graph_data, knowledge_id)
        trace_id = str(uuid4().hex)
        with logger.contextualize(trace_id=trace_id):
            await chat_manager.handle_websocket(
                flow_id,
                chat_id,
                websocket,
                settings.get_from_db('default_operator').get('user'),
                gragh_data=graph_data)
    except Exception as exc:
        logger.error(exc)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))


# @router.get('/source')
# async def query_source(message_id: int, session: Session = Depends(get_session)):
#     """source of message_id"""
#     db_recall = session.query(RecallChunk).where(RecallChunk.message_id == message_id).all()


@router.post('/liked', status_code=200)
def like_response(*, data: dict):
    message_id = data.get('message_id')
    liked = data.get('liked')
    with session_getter() as session:
        message = session.get(ChatMessage, message_id)
        message.liked = liked
        session.add(message)
        session.commit()
    return {'status_code': 200, 'status_message': 'success'}


@router.post('/solved', status_code=200)
def solve_response(*, data: dict):
    chat_id = data.get('chat_id')
    solved = data.get('solved')
    with session_getter() as session:
        messages = session.query(ChatMessage).where(ChatMessage.chat_id == chat_id).all()
    for message in messages:
        message.solved = solved
    with session_getter() as session:
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
                 message_list: List[SyncMessage] = Body(embed=True),
                 user_id: int = Body(default=None, embed=True)):

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
                    chat_id=flow_id.hex) for message in message_list
    ]
    ChatMessageDao.insert_batch(batch_message)
    return resp_200()
