import json
from typing import Optional
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import BuildStatus
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from fastapi import APIRouter, WebSocket, WebSocketException, status

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期
default_user_id = 1


@router.websocket('/chat/ws/{client_id}')
async def union_websocket(client_id: str,
                          websocket: WebSocket,
                          chat_id: Optional[str] = None,
                          type: Optional[str] = None,
                          ):
    """Websocket endpoint forF  chat."""
    if type and type == 'L1':
        with next(get_session()) as session:
            db_flow = session.get(Flow, client_id)
        if not db_flow:
            await websocket.accept()
            message = '该技能已被删除'
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
        if db_flow.status != 2:
            await websocket.accept()
            message = '当前技能未上线，无法直接对话'
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
        graph_data = db_flow.data
    else:
        flow_data_key = 'flow_data_' + client_id
        if str(flow_data_store.hget(flow_data_key, 'status'), 'utf-8') != BuildStatus.SUCCESS.value:
            await websocket.accept()
            message = '当前编译没通过'
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason=message)
        graph_data = json.loads(flow_data_store.hget(flow_data_key, 'graph_data'))

    try:
        process_file = False if chat_id else True
        graph = build_flow_no_yield(graph_data=graph_data,
                                    artifacts={},
                                    process_file=process_file,
                                    flow_id=UUID(client_id).hex,
                                    chat_id=chat_id)
        langchain_object = graph.build()
        for node in langchain_object:
            key_node = get_cache_key(client_id, chat_id, node.id)
            chat_manager.set_cache(key_node, node._built_object)
            chat_manager.set_cache(get_cache_key(client_id, chat_id), node._built_object)
        await chat_manager.handle_websocket(client_id, chat_id, websocket, default_user_id)
    except WebSocketException as exc:
        logger.error(exc)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as e:
        logger.error(str(e))
