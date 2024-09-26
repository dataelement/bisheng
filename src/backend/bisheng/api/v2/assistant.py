# 免登录的助手相关接口
import time
import uuid
from typing import Optional
from uuid import UUID

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import OpenAIChatCompletionResp, OpenAIChatCompletionReq, UnifiedResponseModel, \
    AssistantInfo, OpenAIChoice
from bisheng.api.v2.utils import get_default_operator
from bisheng.api.v1.schemas import (AssistantInfo, OpenAIChatCompletionReq,
                                    OpenAIChatCompletionResp, OpenAIChoice, UnifiedResponseModel)
from bisheng.chat.types import WorkType
from bisheng.settings import settings
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from fastapi.responses import ORJSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

router = APIRouter(prefix='/assistant', tags=['OpenAPI', 'Assistant'])


@router.post('/chat/completions', response_model=OpenAIChatCompletionResp)
async def assistant_chat_completions(request: Request, req_data: OpenAIChatCompletionReq):
    """
    兼容openai接口格式，所有的错误必须返回非http200的状态码
    和助手进行聊天
    """
    logger.info(
        f'act=assistant_chat_completions assistant_id={req_data.model}, ip={get_request_ip(request)}'
    )
    try:
        # 获取系统配置里配置的默认用户信息
        login_user = get_default_operator()
    except Exception as e:
        return ORJSONResponse(status_code=500, content=str(e), media_type='application/json')
    # 查找助手信息
    res = AssistantService.get_assistant_info(UUID(req_data.model), login_user)
    if res.status_code != 200:
        return ORJSONResponse(status_code=500,
                              content=res.status_message,
                              media_type='application/json')

    assistant_info = res.data
    # 覆盖温度设置
    if req_data.temperature != 0:
        assistant_info.temperature = req_data.temperature

    chat_history = []
    question = ''
    # 解析出对话历史和用户最新的问题
    for one in req_data.messages:
        if one['role'] == 'user':
            chat_history.append(HumanMessage(content=one['content']))
            question = one['content']
        elif one['role'] == 'assistant':
            chat_history.append(AIMessage(content=one['content']))
    # 在历史记录里去除用户的问题
    if chat_history and chat_history[-1].content == question:
        chat_history = chat_history[:-1]

    # 初始化助手agent
    agent = AssistantAgent(assistant_info, '')  # 初始化agent
    await agent.init_assistant()
    answer = await agent.run(question, chat_history)
    answer = answer[0].content

    openai_resp_id = uuid.uuid4().hex
    logger.info(f'act=assistant_chat_completions_over openai_resp_id={openai_resp_id}')
    # 将结果包装成openai的数据格式
    openai_resp = OpenAIChatCompletionResp(
        id=openai_resp_id,
        object='chat.completion',
        created=int(time.time()),
        model=req_data.model,
        choices=[OpenAIChoice(index=0, message={
            'role': 'assistant',
            'content': answer
        })],
    )

    # 非流式直接返回结果
    if not req_data.stream:
        return openai_resp

    # 流式返回最终结果, 兼容openai格式处理
    openai_resp.object = 'chat.completion.chunk'
    openai_resp.choices = [OpenAIChoice(index=0, delta={'content': answer})]

    async def _event_stream():
        # todo：zgq 后续优化成真正的流式输出，目前是出现最终答案之后直接流式返回的
        yield f'data: {openai_resp.json()}\n\n'
        # 最后的[DONE]
        yield 'data: [DONE]\n\n'

    try:
        return StreamingResponse(_event_stream(), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        return ORJSONResponse(status_code=500, content=str(exc))


@router.get('/info/{assistant_id}', response_model=UnifiedResponseModel[AssistantInfo])
async def get_assistant_info(request: Request, assistant_id: UUID):
    """
    获取助手信息, 用系统配置里的default_operator.user的用户信息来做权限校验
    """
    logger.info(f'act=get_default_operator assistant_id={assistant_id}, ip={get_request_ip(request)}')
    # 判断下配置是否打开
    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="无权限访问")
    login_user = get_default_operator()
    return AssistantService.get_assistant_info(assistant_id, login_user)


@router.get('/list', status_code=200)
def get_assistant_list(request: Request,
                       name: str = Query(default=None, description='助手名称，模糊匹配, 包含描述的模糊匹配'),
                       tag_id: int = Query(default=None, description='标签ID'),
                       page: Optional[int] = Query(default=1, gt=0, description='页码'),
                       limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                       status: Optional[int] = Query(default=None, description='是否上线状态'),
                       user_id: int = None):
    """
    公开的获取技能信息的接口
    """
    logger.info(f'public_get_list ip: {request.client.host} user_id:{user_id}')

    user_id = user_id if user_id else settings.get_from_db('default_operator').get('user')
    login_user = UserPayload(**{'user_id': user_id, 'role': ''})
    return AssistantService.get_assistant(login_user, name, status, tag_id, page, limit)


@router.websocket('/chat/{assistant_id}')
async def chat(*, websocket: WebSocket, assistant_id: str, chat_id: Optional[str] = None):
    """
    助手的ws免登录接口
    """
    logger.info(f'act=assistant_chat_ws assistant_id={assistant_id}, ip={get_request_ip(websocket)}')
    login_user = get_default_operator()
    try:
        request = websocket
        await chat_manager.dispatch_client(request, assistant_id, chat_id, login_user,
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
