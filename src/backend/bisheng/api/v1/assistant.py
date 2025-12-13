from typing import List, Optional, Union

from fastapi import (APIRouter, Body, Depends, HTTPException, Query, Request, WebSocket,
                     WebSocketException)
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import (AssistantCreateReq, AssistantUpdateReq,
                                    StreamData, resp_200)
from bisheng.chat.manager import ChatManager
from bisheng.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.schemas.api import PageData
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.assistant import Assistant
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import generate_uuid

router = APIRouter(prefix='/assistant', tags=['Assistant'])
chat_manager = ChatManager()


@router.get('')
def get_assistant(*,
                  name: str = Query(default=None, description='助手名称，模糊匹配, 包含描述的模糊匹配'),
                  tag_id: int = Query(default=None, description='标签ID'),
                  page: Optional[int] = Query(default=1, gt=0, description='页码'),
                  limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                  status: Optional[int] = Query(default=None, description='是否上线状态'),
                  login_user: UserPayload = Depends(UserPayload.get_login_user)):
    data, total = AssistantService.get_assistant(login_user, name, status, tag_id, page, limit)
    return resp_200(PageData(data=data, total=total))


# 获取某个助手的详细信息
@router.get('/info/{assistant_id}')
async def get_assistant_info(*, assistant_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user),
                             share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    """获取助手信息"""
    res = await AssistantService.get_assistant_info(assistant_id, login_user, share_link)
    return resp_200(data=res)


@router.post('/delete')
def delete_assistant(*,
                     request: Request,
                     assistant_id: str,
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """删除助手"""
    AssistantService.delete_assistant(request, login_user, assistant_id)
    return resp_200()


@router.post('')
async def create_assistant(*,
                           request: Request,
                           req: AssistantCreateReq,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    assistant = Assistant(**req.model_dump(), user_id=login_user.user_id)
    res = await AssistantService.create_assistant(request, login_user, assistant)
    return resp_200(data=res)


@router.put('')
async def update_assistant(*,
                           request: Request,
                           req: AssistantUpdateReq,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    assistant_model = await AssistantService.update_assistant(request, login_user, req)
    return resp_200(data=assistant_model)


@router.post('/status')
async def update_status(*,
                        request: Request,
                        assistant_id: str = Body(description='助手唯一ID', alias='id'),
                        status: int = Body(description='是否上线，1:上线，0:下线'),
                        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    await AssistantService.update_status(request, login_user, assistant_id, status)
    return resp_200()


@router.post('/auto/task')
async def auto_update_assistant_task(*, request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                                     assistant_id: str = Body(description='助手唯一ID'),
                                     prompt: str = Body(description='用户填写的提示词')):
    # 存入缓存
    task_id = generate_uuid()
    redis_client = await get_redis_client()
    await redis_client.aset(f'auto_update_task:{task_id}', {
        'assistant_id': assistant_id,
        'prompt': prompt,
    })
    return resp_200(data={
        'task_id': task_id
    })


# 自动优化prompt和工具选择
@router.get('/auto', response_class=StreamingResponse)
async def auto_update_assistant(*, task_id: str = Query(description='优化任务唯一ID'),
                                login_user: UserPayload = Depends(UserPayload.get_login_user)):
    redis_client = await get_redis_client()
    task = await redis_client.aget(f'auto_update_task:{task_id}')
    if not task:
        raise NotFoundError()
    assistant_id = task['assistant_id']
    prompt = task['prompt']

    async def event_stream():
        try:
            async for message in AssistantService.auto_update_stream(assistant_id, prompt, login_user):
                yield message
            yield str(StreamData(event='message', data={'type': 'end', 'data': ''}))
        except Exception as e:
            logger.exception('assistant auto update error')
            yield str(StreamData(event='message', data={'type': 'end', 'message': str(e)}))

    return StreamingResponse(event_stream(), media_type='text/event-stream')


# 更新助手的提示词
@router.post('/prompt')
async def update_prompt(*,
                        assistant_id: str = Body(description='助手唯一ID', alias='id'),
                        prompt: str = Body(description='用户使用的prompt'),
                        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    AssistantService.update_prompt(assistant_id, prompt, login_user)
    return resp_200()


@router.post('/flow')
async def update_flow_list(*,
                           assistant_id: str = Body(description='助手唯一ID', alias='id'),
                           flow_list: List[str] = Body(description='用户选择的技能列表'),
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    AssistantService.update_flow_list(assistant_id, flow_list, login_user)
    return resp_200()


@router.post('/tool')
async def update_tool_list(*,
                           assistant_id: str = Body(description='助手唯一ID', alias='id'),
                           tool_list: List[int] = Body(description='用户选择的工具列表'),
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ 更新助手选择的工具列表 """
    AssistantService.update_tool_list(assistant_id, tool_list, login_user)
    return resp_200()


# 助手对话的websocket连接
@router.websocket('/chat/{assistant_id}')
async def chat(*,
               assistant_id: str,
               websocket: WebSocket,
               chat_id: Optional[str] = None,
               login_user: UserPayload = Depends(UserPayload.get_login_user_from_ws)):
    try:
        await chat_manager.dispatch_client(websocket, assistant_id, chat_id, login_user,
                                           WorkType.GPTS, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as exc:
        logger.exception(f'Error in chat websocket: {str(exc)}')
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if 'Could not validate credentials' in str(exc):
            await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason='Unauthorized')
        else:
            await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=message)
