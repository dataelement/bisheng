from typing import Optional
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.knowledge import Knowledge
from bisheng.database.models.message import ChatMessage
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from fastapi import APIRouter, Depends, WebSocket, status
from sqlmodel import Session

router = APIRouter(prefix='/chat', tags=['Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期


@router.websocket('/ws/{flow_id}')
async def union_websocket(flow_id: str,
                          websocket: WebSocket,
                          chat_id: Optional[str] = None,
                          type: Optional[str] = None,
                          knowledge_id: Optional[int] = None,
                          session: Session = Depends(get_session)):
    """Websocket endpoint forF  chat."""
    if type and type == 'L1':
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
        process_file = False if chat_id else True
        if knowledge_id:
            knowledge = session.get(Knowledge, knowledge_id)
        else:
            knowledge = None

        graph = build_flow_no_yield(
            graph_data=graph_data,
            artifacts={},
            process_file=process_file,
            flow_id=UUID(flow_id).hex,
            chat_id=chat_id,
            collection_name=knowledge.collection_name if knowledge else None,
        )
        langchain_object = graph.build()
        for node in langchain_object:
            key_node = get_cache_key(flow_id, chat_id, node.id)
            chat_manager.set_cache(key_node, node._built_object)
            chat_manager.set_cache(get_cache_key(flow_id, chat_id), node._built_object)
        await chat_manager.handle_websocket(flow_id, chat_id, websocket,
                                            settings.get_from_db('default_operator').get('user'))
    except Exception as exc:
        logger.error(exc)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))


# @router.get('/source')
# async def query_source(message_id: int, session: Session = Depends(get_session)):
#     """source of message_id"""
#     db_recall = session.query(RecallChunk).where(RecallChunk.message_id == message_id).all()


@router.post('/liked', status_code=200)
def like_response(
        *,
        data: dict,
        session: Session = Depends(get_session),
):
    message_id = data.get('message_id')
    liked = data.get('liked')
    message = session.get(ChatMessage, message_id)
    message.liked = liked
    session.add(message)
    session.commit()
    return {'status_code': 200, 'status_message': 'success'}


@router.post('/solved', status_code=200)
def solve_response(
        *,
        data: dict,
        session: Session = Depends(get_session),
):
    chat_id = data.get('chat_id')
    solved = data.get('solved')
    messages = session.query(ChatMessage).where(ChatMessage.chat_id == chat_id).all()
    for message in messages:
        message.solved = solved
    session.commit()
    return {'status_code': 200, 'status_message': 'success'}
