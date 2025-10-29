# 免登录的助手相关接口
import json
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from fastapi.responses import ORJSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, AIMessageChunk
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import (OpenAIChatCompletionReq,
                                    OpenAIChatCompletionResp, OpenAIChoice)
from bisheng.api.v2.utils import get_default_operator
from bisheng.chat.types import WorkType
from bisheng.common.services.config_service import settings
from bisheng.utils import generate_uuid
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/assistant', tags=['OpenAPI', 'Assistant'])


@router.post('/chat/completions')
async def assistant_chat_completions(request: Request, req_data: OpenAIChatCompletionReq):
    """
    兼容openai接口格式，所有的错误必须返回非http200的状态码
    和助手进行聊天
    
    实现需求：
    1. 判断助手调用的模型是否支持流式调用
    2. 如果不支持则按原逻辑走
    3. 如果支持并且stream=True，采用真实的流式调用
    4. stream=False 还是按照原来的逻辑返回JSON
    """
    assistant_id = UUID(req_data.model).hex
    logger.info(
        f'act=assistant_chat_completions assistant_id={req_data.model}, stream={req_data.stream}, ip={get_request_ip(request)}'
    )
    try:
        # 获取系统配置里配置的默认用户信息
        login_user = get_default_operator()
    except Exception as e:
        return ORJSONResponse(status_code=500, content=str(e), media_type='application/json')
    # 查找助手信息
    res = AssistantService.get_assistant_info(assistant_id, login_user)
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
    agent = AssistantAgent(assistant_info, '')
    await agent.init_assistant()

    # 判断模型是否支持流式调用
    model_supports_streaming = _check_model_supports_streaming(agent)

    logger.debug(
        f'act=assistant_chat_completions model_supports_streaming={model_supports_streaming}, stream={req_data.stream}, llm_type={type(agent.llm)}')
    # 非流式调用或模型不支持流式
    if not req_data.stream or not model_supports_streaming:
        answer = await agent.run(question, chat_history)
        answer = answer[-1].content

        openai_resp_id = generate_uuid()

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

        # 用户要求流式但模型不支持，使用伪流式返回
        openai_resp.object = 'chat.completion.chunk'
        openai_resp.choices = [OpenAIChoice(index=0, delta={'content': answer})]

        async def _pseudo_event_stream():
            yield f'data: {openai_resp.json()}\n\n'
            yield 'data: [DONE]\n\n'

        return StreamingResponse(_pseudo_event_stream(), media_type='text/event-stream')

    # 模型支持流式且用户要求流式，使用真实的流式调用
    openai_resp_id = generate_uuid()
    logger.info(f'act=assistant_chat_completions_streaming openai_resp_id={openai_resp_id}')

    async def _streaming_event_generator():
        """真实的流式事件生成器"""
        logger.debug(f'[API流式] _streaming_event_generator开始执行')
        try:

            # 使用真正的流式调用
            chunk_counter = 0
            try:
                async for message_chunk in agent.astream(question, chat_history):
                    chunk_counter += 1

                    if not message_chunk:
                        logger.debug(f'Empty message_chunk received')
                        continue
                    # 获取最新的消息
                    latest_message = message_chunk[-1] if isinstance(message_chunk, list) else message_chunk
                    if not isinstance(latest_message, AIMessageChunk):
                        continue
                    reasoning_content = latest_message.additional_kwargs.get("reasoning_content", "")
                    content = latest_message.content

                    chunk_data = {
                        "id": openai_resp_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": req_data.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content, "reasoning_content": reasoning_content},
                            "finish_reason": None
                        }]
                    }
                    # 使用更安全的JSON序列化，避免传输截断
                    json_str = json.dumps(chunk_data, ensure_ascii=False, separators=(',', ':'))
                    yield f'data: {json_str}\n\n'
            except Exception as astream_error:
                logger.exception('[API流式] agent.astream()调用出错')
                raise astream_error

            logger.info(f'[API流式] astream循环结束，总共处理了{chunk_counter}个chunk')

            # 发送结束信号
            end_chunk = {
                "id": openai_resp_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": req_data.model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }
            yield f'data: {json.dumps(end_chunk, ensure_ascii=False)}\n\n'
            yield 'data: [DONE]\n\n'

        except Exception as exc:
            logger.error(f'Streaming error: {exc}')
            # 发送错误信息
            error_chunk = {
                "id": openai_resp_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": req_data.model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"错误: {str(exc)}"},
                    "finish_reason": "stop"
                }]
            }
            yield f'data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n'
            yield 'data: [DONE]\n\n'

    try:
        logger.info(f'[API流式] 创建StreamingResponse，生成器函数: {_streaming_event_generator}')
        return StreamingResponse(_streaming_event_generator(),
                                 media_type='text/event-stream')
    except Exception as exc:
        logger.error(f'StreamingResponse creation error: {exc}')
        return ORJSONResponse(status_code=500, content=str(exc))


def _check_model_supports_streaming(agent: AssistantAgent) -> bool:
    """
    检查助手调用的模型是否支持流式调用
    
    Args:
        agent: 助手代理实例
        
    Returns:
        bool: 是否支持流式调用
    """
    try:
        # 检查agent的LLM是否支持流式
        if hasattr(agent, 'llm') and agent.llm:
            # 检查BishengLLM的streaming属性
            if hasattr(agent.llm, 'streaming'):
                return agent.llm.streaming
            # 检查底层llm的stream属性
            elif hasattr(agent.llm, 'llm') and hasattr(agent.llm.llm, 'streaming'):
                return agent.llm.llm.streaming

        # 如果无法判断，默认支持流式（大多数现代LLM都支持）
        return True
    except Exception as e:
        logger.warning(f'Failed to check streaming support: {e}')
        # 出错时默认支持流式
        return True


@router.get('/info/{assistant_id}')
async def get_assistant_info(request: Request, assistant_id: UUID):
    """
    获取助手信息, 用系统配置里的default_operator.user的用户信息来做权限校验
    """
    assistant_id = assistant_id.hex
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

    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="无权限访问")
    login_user = get_default_operator()
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
