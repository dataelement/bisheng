import json
import os
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException, Request
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from fastapi_jwt_auth import AuthJWT
from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.chat.types import WorkType

router = APIRouter(prefix='/workflow', tags=['Workflow'])


@router.get('/template', response_model=UnifiedResponseModel, status_code=200)
def get_template():
    """ 获取节点模板的接口 """
    # todo: 改为template class 管理
    current_path = os.path.dirname(os.path.abspath(__file__))
    with open(f"{current_path}/workflow_template.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    return resp_200(data=data)


@router.websocket('/chat/{workflow_id}')
async def workflow_ws(*,
                      workflow_id: str,
                      websocket: WebSocket,
                      t: Optional[str] = None,
                      chat_id: Optional[str] = None,
                      Authorize: AuthJWT = Depends()):
    try:
        # if t:
        #     Authorize.jwt_required(auth_from='websocket', token=t)
        #     Authorize._token = t
        # else:
        #     Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        #
        # payload = Authorize.get_jwt_subject()
        # payload = json.loads(payload)
        payload = {
            'user_id': 1,
            'user_name': 'admin',
            'role': 'admin',
        }
        login_user = UserPayload(**payload)
        await chat_manager.dispatch_client(websocket, workflow_id, chat_id, login_user, WorkType.WORKFLOW, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
