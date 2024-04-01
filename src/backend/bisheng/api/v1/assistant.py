import json
from typing import List, Optional
from uuid import UUID

from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import (AssistantCreateReq, AssistantInfo, AssistantUpdateReq,
                                    UnifiedResponseModel, resp_200, resp_500)
from bisheng.chat.manager import ChatManager
from bisheng.chat.types import WorkType
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.gpts_tools import GptsToolsRead
from bisheng.utils.logger import logger
from fastapi import (APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException,
                     status)
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/assistant', tags=['Assistant'])
chat_manager = ChatManager()


@router.get('', response_model=UnifiedResponseModel[List[AssistantInfo]])
def get_assistant(*,
                  name: str = Query(default=None, description='助手名称，模糊匹配'),
                  page: Optional[int] = Query(default=1, description='页码'),
                  limit: Optional[int] = Query(default=10, description='每页条数'),
                  status: Optional[int] = Query(default=None, description='是否上线状态'),
                  Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return AssistantService.get_assistant(current_user.get('user_id'), name, status, page, limit)


# 获取某个助手的详细信息
@router.get('/info/{assistant_id}', response_model=UnifiedResponseModel[AssistantInfo])
def get_assistant_info(*, assistant_id: UUID, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return AssistantService.get_assistant_info(assistant_id, current_user.get('user_id'))


@router.post('/delete', response_model=UnifiedResponseModel)
def delete_assistant(*, assistant_id: UUID, Authorize: AuthJWT = Depends()):
    """删除助手"""
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    try:
        AssistantService.delete_assistant(assistant_id, current_user.get('user_id'))
        return resp_200()
    except Exception as e:
        return resp_500(str(e))


@router.post('', response_model=UnifiedResponseModel[AssistantInfo])
async def create_assistant(*, req: AssistantCreateReq, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    assistant = Assistant(**req.dict(), user_id=current_user.get('user_id'))
    return AssistantService.create_assistant(assistant)


@router.put('', response_model=UnifiedResponseModel[AssistantInfo])
async def update_assistant(*, req: AssistantUpdateReq, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    return AssistantService.update_assistant(req)


# 自动优化prompt和工具选择
@router.post('/auto', response_model=UnifiedResponseModel[AssistantInfo])
async def auto_update_assistant(*,
                                assistant_id: UUID = Body(description='助手唯一ID'),
                                prompt: str = Body(description='用户填写的提示词'),
                                Authorize: AuthJWT = Depends()):
    return AssistantService.auto_update(assistant_id, prompt)


# 更新助手的提示词
@router.post('/prompt', response_model=UnifiedResponseModel)
async def update_prompt(*,
                        assistant_id: UUID = Body(description='助手唯一ID'),
                        prompt: str = Body(description='用户使用的prompt'),
                        Authorize: AuthJWT = Depends()):
    return AssistantService.update_prompt(assistant_id, prompt)


@router.post('/flow', response_model=UnifiedResponseModel)
async def update_flow_list(*,
                           assistant_id: UUID = Body(description='助手唯一ID'),
                           flow_list: List[str] = Body(description='用户选择的技能列表'),
                           Authorize: AuthJWT = Depends()):
    return AssistantService.update_flow_list(assistant_id, flow_list)


@router.post('/tool', response_model=UnifiedResponseModel)
async def update_tool_list(*,
                           assistant_id: UUID = Body(description='助手唯一ID'),
                           tool_list: List[int] = Body(description='用户选择的工具列表'),
                           Authorize: AuthJWT = Depends()):
    return AssistantService.update_tool_list(assistant_id, tool_list)


# 获取助手可用的模型列表
@router.get('/models', response_model=UnifiedResponseModel)
async def get_models(*, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    return AssistantService.get_models()


# 助手对话的websocket连接
@router.websocket('/chat/{assistant_id}')
async def chat(*,
               assistant_id: str,
               websocket: WebSocket,
               t: Optional[str] = None,
               chat_id: Optional[str] = None,
               Authorize: AuthJWT = Depends()):
    try:
        if t:
            Authorize.jwt_required(auth_from='websocket', token=t)
            Authorize._token = t
        else:
            Authorize.jwt_required(auth_from='websocket', websocket=websocket)

        payload = Authorize.get_jwt_subject()
        payload = json.loads(payload)
        user_id = payload.get('user_id')
        await chat_manager.dispatch_client(assistant_id, chat_id, user_id, WorkType.GPTS,
                                           websocket)

    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as exc:
        logger.exception(f'Error in chat websocket: {str(exc)}')
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if 'Could not validate credentials' in str(exc):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason='Unauthorized')
        else:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=message)


@router.get('/tool_list', response_model=UnifiedResponseModel[GptsToolsRead])
def get_tool_list(*, Authorize: AuthJWT = Depends()):
    """查询所有可见的tool 列表"""
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return resp_200(AssistantService.get_gpts_tools(current_user))
