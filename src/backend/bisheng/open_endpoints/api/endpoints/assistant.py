# Login-free assistant related interface
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
from bisheng.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.schemas.api import resp_200, PageData
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.open_endpoints.domain.utils import get_default_operator
from bisheng.utils import generate_uuid
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/assistant', tags=['OpenAPI', 'Assistant'])


@router.post('/chat/completions')
async def assistant_chat_completions(request: Request, req_data: OpenAIChatCompletionReq):
    """
    Compatible openaiInterface format, all errors must return non-http200Status code
    Chat with your assistant
    
    Fulfillment needs:
    1. Determine if the model invoked by the assistant supports streaming calls
    2. If not, follow the original logic
    3. If supported andstream=True, with real streaming calls
    4. stream=False Or return to the original logic?JSON
    """
    assistant_id = UUID(req_data.model).hex
    logger.info(
        f'act=assistant_chat_completions assistant_id={req_data.model}, stream={req_data.stream}, ip={get_request_ip(request)}'
    )
    try:
        # Get the default user information configured in the system configuration
        login_user = get_default_operator()
    except Exception as e:
        return ORJSONResponse(status_code=500, content=str(e), media_type='application/json')
    # Find Assistant Information
    try:
        assistant_info = await AssistantService.get_assistant_info(assistant_id, login_user)
    except Exception as e:
        return ORJSONResponse(status_code=500,
                              content=str(e),
                              media_type='application/json')

    start_time = time.time()
    try:
        # Overlay Temperature Settings
        if req_data.temperature != 0:
            assistant_info.temperature = req_data.temperature

        chat_history = []
        question = ''
        # Resolve the conversation history and the user's latest questions
        for one in req_data.messages:
            if one['role'] == 'user':
                chat_history.append(HumanMessage(content=one['content']))
                question = one['content']
            elif one['role'] == 'assistant':
                chat_history.append(AIMessage(content=one['content']))
        # Remove user issue from history
        if chat_history and chat_history[-1].content == question:
            chat_history = chat_history[:-1]

        # Initialization Assistantagent
        agent = AssistantAgent(assistant_info, '', invoke_user_id=login_user.user_id)
        await agent.init_assistant()

        # Determine if the model supports streaming calls
        model_supports_streaming = _check_model_supports_streaming(agent)

        logger.debug(
            f'act=assistant_chat_completions model_supports_streaming={model_supports_streaming}, stream={req_data.stream}, llm_type={type(agent.llm)}')
        # Streaming is not supported for non-streaming calls or models
        if not req_data.stream or not model_supports_streaming:
            answer = await agent.run(question, chat_history)
            answer = answer[-1].content

            openai_resp_id = generate_uuid()

            # Package the results asopenaiData Format
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

            # Non-streaming direct return results
            if not req_data.stream:
                return openai_resp

            # The user requests streaming but the model does not support it, use pseudo-streaming to return
            openai_resp.object = 'chat.completion.chunk'
            openai_resp.choices = [OpenAIChoice(index=0, delta={'content': answer})]

            async def _pseudo_event_stream():
                yield f'data: {openai_resp.json()}\n\n'
                yield 'data: [DONE]\n\n'

            return StreamingResponse(_pseudo_event_stream(), media_type='text/event-stream')

        # Model supports streaming and user-requested streaming, using real streaming calls
        openai_resp_id = generate_uuid()
        logger.info(f'act=assistant_chat_completions_streaming openai_resp_id={openai_resp_id}')

        async def _streaming_event_generator():
            """Real Streaming Event Generator"""
            logger.debug(f'[APIStreamed] _streaming_event_generatorto process')
            try:

                # Use True Streaming Calls
                chunk_counter = 0
                try:
                    async for message_chunk in agent.astream(question, chat_history):
                        chunk_counter += 1

                        if not message_chunk:
                            logger.debug(f'Empty message_chunk received')
                            continue
                        # Get the latest news
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
                        # Use saferJSONSerialization to avoid transmission truncation
                        json_str = json.dumps(chunk_data, ensure_ascii=False, separators=(',', ':'))
                        yield f'data: {json_str}\n\n'
                except Exception as astream_error:
                    logger.exception('[APIStreamed] agent.astream()Error calling')
                    raise astream_error

                logger.info(f'[APIStreamed] astreamLoop ended, total processed{chunk_counter}Pcschunk')

                # Send End Signal
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
                # Send error message
                error_chunk = {
                    "id": openai_resp_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req_data.model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"Error-free: {str(exc)}"},
                        "finish_reason": "stop"
                    }]
                }
                yield f'data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n'
                yield 'data: [DONE]\n\n'

        try:
            logger.info(f'[APIStreamed] BuatStreamingResponse, generator function: {_streaming_event_generator}')
            return StreamingResponse(_streaming_event_generator(),
                                     media_type='text/event-stream')
        except Exception as exc:
            logger.error(f'StreamingResponse creation error: {exc}')
            return ORJSONResponse(status_code=500, content=str(exc))
    finally:
        end_time = time.time()
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=assistant_id,
                                              app_name=assistant_info.name,
                                              app_type=ApplicationTypeEnum.ASSISTANT,
                                              chat_id='',
                                              start_time=int(start_time),
                                              end_time=int(end_time)))
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationProcessEventData(
                                              app_id=assistant_id,
                                              app_name=assistant_info.name,
                                              app_type=ApplicationTypeEnum.ASSISTANT,
                                              chat_id='',
                                              start_time=int(start_time),
                                              end_time=int(end_time),
                                              process_time=int((end_time - start_time) * 1000)
                                          ))


def _check_model_supports_streaming(agent: AssistantAgent) -> bool:
    """
    Check whether the model called by the helper supports streaming calls
    Args:
        agent: Assistant Proxy Instance
    Returns:
        bool: Does it support streaming calls?
    """
    try:
        # Othersagentright of privacyLLMDoes it support streaming?
        if hasattr(agent, 'llm') and agent.llm:
            # OthersBishengLLMright of privacystreamingProperty
            if hasattr(agent.llm, 'streaming'):
                return agent.llm.streaming
            # Check Bottom Layerllmright of privacystreamProperty
            elif hasattr(agent.llm, 'llm') and hasattr(agent.llm.llm, 'streaming'):
                return agent.llm.llm.streaming

        # If it cannot be determined, streaming is supported by default (most modernLLMare supported)
        return True
    except Exception as e:
        logger.warning(f'Failed to check streaming support: {e}')
        # Streaming is supported by default when an error occurs
        return True


@router.get('/info/{assistant_id}')
async def get_assistant_info(request: Request, assistant_id: UUID):
    """
    Getting Helper Information, Use the system configuration indefault_operator.userUser information to verify permissions
    """
    assistant_id = assistant_id.hex
    logger.info(f'act=get_default_operator assistant_id={assistant_id}, ip={get_request_ip(request)}')
    # Determine if the configuration under is turned on
    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="No permission to access")
    login_user = get_default_operator()
    res = await AssistantService.get_assistant_info(assistant_id, login_user)
    return resp_200(data=res)


@router.get('/list', status_code=200)
def get_assistant_list(request: Request,
                       name: str = Query(default=None, description='assistant name, fuzzy matching, Fuzzy matches with description'),
                       tag_id: int = Query(default=None, description='labelID'),
                       page: Optional[int] = Query(default=1, gt=0, description='Page'),
                       limit: Optional[int] = Query(default=10, gt=0, description='Listings Per Page'),
                       status: Optional[int] = Query(default=None, description='Is online status'),
                       user_id: int = None):
    """
    Exposed interfaces for obtaining skill information
    """
    logger.info(f'public_get_list ip: {request.client.host} user_id:{user_id}')

    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="No permission to access")
    login_user = get_default_operator()
    data, total = AssistantService.get_assistant(login_user, name, status, tag_id, page, limit)
    return resp_200(PageData(data=data, total=total))


@router.websocket('/chat/{assistant_id}')
async def chat(*, websocket: WebSocket, assistant_id: str, chat_id: Optional[str] = None):
    """
    Assistant'swsLogin-Free Interface
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
