import json
import os
from typing import Optional
from uuid import uuid4

from bisheng_langchain.utils.requests import Requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException, Request
from fastapi import status as http_status
from fastapi_jwt_auth import AuthJWT
from loguru import logger

from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.chat.types import WorkType
from bisheng.utils import minio_client

router = APIRouter(prefix='/workflow', tags=['Workflow'])


@router.get('/template', response_model=UnifiedResponseModel, status_code=200)
def get_template():
    """ 获取节点模板的接口 """
    # todo: 改为template class 管理
    current_path = os.path.dirname(os.path.abspath(__file__))
    with open(f"{current_path}/workflow_template.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    return resp_200(data=data)


@router.get("/report/file", response_model=UnifiedResponseModel, status_code=200)
async def get_report_file(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
        version_key: str = Query("", description="minio的object_name")):
    """ 获取report节点的模板文件 """
    if not version_key:
        # 重新生成一个version_key
        version_key = f"bisheng/workflow/{uuid4().hex}.docx"
    file_url = minio_client.MinioClient().get_share_link(version_key)
    return resp_200(data={
        'url': file_url,
        'version_key': version_key,
    })


@router.post('/report/callback', response_model=UnifiedResponseModel, status_code=200)
async def upload_report_file(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
        data: dict = Body(...)):
    """ office 回调接口保存 report节点的模板文件 """
    status = data.get('status')
    file_url = data.get('url')
    key = data.get('key')
    logger.debug(f'callback={data}')
    if status not in {2, 6}:
        # 非保存回调不处理
        return {'error': 0}
    logger.info(f'office_callback url={file_url}')
    file = Requests().get(url=file_url)
    minio_client.MinioClient().upload_minio_data(
        key, file._content, len(file._content),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')


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
