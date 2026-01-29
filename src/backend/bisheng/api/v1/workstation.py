import asyncio
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, List, Type, Tuple
from urllib.parse import unquote
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sse_starlette import EventSourceResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.services.workstation import (WorkstationConversation,
                                              WorkstationMessage, WorkStationService)
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, SSEResponse, delta
from bisheng.api.v1.schemas import FrequentlyUsedChat
from bisheng.api.v1.schemas import WorkstationConfig, resp_200, ExcelRule, UnifiedResponseModel
from bisheng.chat.utils import SourceType, process_source_document
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.common.errcode.workstation import WebSearchToolNotFoundError, ConversationNotFoundError, \
    AgentAlreadyExistsError
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData, ApplicationAliveEventData, \
    ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import save_download_file, save_uploaded_file, async_file_download
from bisheng.core.logger import trace_id_var
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.llm import BishengLLM
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/workstation', tags=['WorkStation'])

titleInstruction = 'a concise, 5-word-or-less title for the conversation, using its same language, with no punctuation. Apply title case conventions appropriate for the language. Never directly mention the language name or the word "title"'  # noqa
promptSearch = '用户的问题是：%s \
判断用户的问题是否需要联网搜索，如果需要返回数字1，如果不需要返回数字0。只返回1或0，不要返回其他信息。\
如果问题涉及到实时信息、最新事件或特定数据库查询等超出你知识截止日期（2024年7月）的内容，就需要进行联网搜索来获取最新信息。'

visual_model_file_types = ['png', 'jpg', 'jpeg', 'webp', 'gif']


# Customizable JSON Serializer
def custom_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert To ISO 8601 Format String
    raise TypeError(f'Type {type(obj)} not serializable')


def user_message(msgId, conversationId, sender, text):
    msg = json.dumps({
        'message': {
            'messageId': msgId,
            'conversationId': conversationId,
            'sender': sender,
            'text': text
        },
        'created': True
    })
    return f'event: message\ndata: {msg}\n\n'


def step_message(stepId, runId, index, msgId):
    msg = json.dumps({
        'event': 'on_run_step',
        'data': {
            'id': stepId,
            'runId': runId,
            'type': 'message_creation',
            'index': index,
            'stepDetails': {
                'type': 'message_creation',
                'message_creation': {
                    'message_id': msgId
                }
            }
        }
    })
    return f'event: message\ndata: {msg}\n\n'


async def final_message(conversation: MessageSession, title: str, requestMessage: ChatMessage, text: str,
                        error: bool, modelName: str, source_document: List[Document] = None):
    responseMessage = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id='',
            type='assistant',
            is_bot=True,
            message=text,
            category='answer',
            sender=modelName,
            extra=json.dumps({
                'parentMessageId': requestMessage.id,
                'error': error
            }),
            source=SourceType.FILE.value if source_document else SourceType.NOT_SUPPORT.value
        ))
    if source_document:
        # Asynchronous processing traceability information storage
        asyncio.create_task(process_source_document(source_document=source_document,
                                                    chat_id=conversation.chat_id,
                                                    message_id=responseMessage.id,
                                                    answer=text))

    # Last message time to update session
    msg = json.dumps(
        {
            'final': True,
            'conversation': WorkstationConversation.from_chat_session(conversation).model_dump(),
            'title': title,
            'requestMessage': (await WorkstationMessage.from_chat_message(requestMessage)).model_dump(),
            'responseMessage': (await WorkstationMessage.from_chat_message(responseMessage)).model_dump(),
        },
        default=custom_json_serializer)
    return f'event: message\ndata: {msg}\n\n'


@router.get('/config', summary='Get workbench configuration', response_model=UnifiedResponseModel)
def get_config(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get model configurations related to reviews """
    ret = WorkStationService.get_config()

    etl_for_lm_url = bisheng_settings.get_knowledge().etl4lm.url
    ret = ret.model_dump() if ret else {}

    ret['enable_etl4lm'] = bool(etl_for_lm_url)
    linsight_invitation_code = bisheng_settings.get_all_config().get('linsight_invitation_code', None)
    ret['linsight_invitation_code'] = linsight_invitation_code if linsight_invitation_code else False
    ret['linsight_cache_dir'] = "./"
    ret['waiting_list_url'] = bisheng_settings.get_linsight_conf().waiting_list_url

    return resp_200(data=ret)


@router.post('/config', summary='Update workbench configuration', response_model=UnifiedResponseModel)
def update_config(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_admin_user),
        data: WorkstationConfig = Body(..., description='Default Model Configuration'),
):
    """ Update model configurations related to reviews """
    ret = WorkStationService.update_config(request, login_user, data)
    return resp_200(data=ret)


@router.post('/knowledgeUpload')
def knowledgeUpload(request: Request,
                    background_tasks: BackgroundTasks,
                    file: UploadFile = File(...),
                    login_user: UserPayload = Depends(UserPayload.get_login_user)):
    try:
        file_path = save_download_file(file.file, 'bisheng', file.filename)
        res = WorkStationService.uploadPersonalKnowledge(request,
                                                         login_user,
                                                         file_path=file_path,
                                                         background_tasks=background_tasks)
        return resp_200(data=res[0])
    except Exception as e:
        raise ServerError(msg=f'Knowledge base upload failed: {str(e)}', exception=e)
    finally:
        file.file.close()


@router.get('/queryKnowledge')
def queryKnoledgeList(request: Request,
                      page: int,
                      size: int,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # Check if there is a personal knowledge base
    res, total = WorkStationService.queryKnowledgeList(request, login_user, page, size)
    return resp_200(data={'list': res, 'total': total})


@router.delete('/deleteKnowledge')
def deleteKnowledge(request: Request,
                    file_id: int,
                    login_user: UserPayload = Depends(UserPayload.get_login_user)):
    res = KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(data=res)


@router.post('/files')
async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        file_id: str = Body(..., description='Doc.ID'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """
    Upload file
    """
    try:

        # Read file contents
        # Save file
        file_path = await save_uploaded_file(file, 'bisheng', unquote(file.filename))

        # Return to file path
        return resp_200(
            data={
                'filepath': file_path,
                'filename': unquote(file.filename),
                'type': file.content_type,
                'user': login_user.user_id,
                '_id': uuid4().hex,
                'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'updatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'temp_file_id': file_id,
                'file_id': uuid4().hex,
                'message': 'File uploaded successfully',
                'context': 'message_attachment',
            })
    except Exception as e:
        raise ServerError(msg=f'File upload failed: {str(e)}', exception=e)
    finally:
        await file.close()


@router.post('/gen_title')
async def gen_title(conversationId: str = Body(..., description='', embed=True),
                    login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Generate Title
    """
    # Get session messages
    redis_key = f'workstation_title_{conversationId}'
    redis_client = await get_redis_client()

    title = await redis_client.aget(redis_key)
    if not title:
        await asyncio.sleep(5)
        # If the title already exists, go straight back to
        title = await redis_client.aget(redis_key)
    if title:
        # If the title already exists, go straight back to
        await redis_client.adelete(redis_key)
        return resp_200({'title': title})
    else:
        return resp_200({'title': 'New Chat'})


@router.get('/messages/{conversationId}')
async def get_chat_history(conversationId: str,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           share_link: Union['ShareLink', None] = Depends(header_share_token_parser)
                           ):
    messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversationId, limit=1000)
    if messages:

        if login_user.user_id != messages[0].user_id:
            # Verify sharing link permissions
            if not share_link or share_link.resource_id != conversationId:
                return UnAuthorizedError.return_resp()

        return resp_200([await WorkstationMessage.from_chat_message(message) for message in messages])
    else:
        return resp_200([])


async def genTitle(human: str, assistant: str, llm: BishengLLM, conversationId: str, login_user: UserPayload,
                   request: Request):
    """
    Generate Title
    """
    convo = f'||>User:\n"{human}"\n ||>Response:\n"{assistant}"'
    prompt = f'Please generate {titleInstruction} \n{convo} \n||>Title:'
    logger.info(f'convo: {convo}')
    res = await llm.ainvoke(prompt)
    title = res.content
    redis_client = await get_redis_client()
    await redis_client.aset(f'workstation_title_{conversationId}', title)
    session = await MessageSessionDao.async_get_one(conversationId)
    if session:
        session.flow_name = title[:200]
        session = await MessageSessionDao.async_insert_one(session)
        # Audit log
        await AuditLogService.create_chat_message(user=login_user, ip_address=get_request_ip(request), message=session)


async def webSearch(query: str, user_id: int):
    """
    Internet search
    """
    web_search_info = GptsToolsDao.get_tool_by_tool_key("web_search")
    if not web_search_info:
        raise WebSearchToolNotFoundError(exception=Exception("No web_search tool found in database"))
    web_search_tool = await ToolExecutor.init_by_tool_id(web_search_info.id,
                                                         app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                                                         app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                                                         app_type=ApplicationTypeEnum.DAILY_CHAT,
                                                         user_id=user_id)
    if not web_search_tool:
        raise WebSearchToolNotFoundError(exception=Exception("No web_search tool found in gpts tools"))
    search_list = await web_search_tool.ainvoke(input={"query": query})
    search_list = json.loads(search_list)
    search_res = ""
    for index, one in enumerate(search_list):
        search_res += f'[webpage ${index} begin]\n${one.get("snippet")}\n[webpage ${index} end]\n\n'
    return search_res, search_list


async def getFileContent(filepath_local: str, file_name, invoke_user_id: int):
    """
    Get file contents
    """
    raw_texts, _, _, _ = await knowledge_imp.async_read_chunk_text(
        invoke_user_id,
        filepath_local,
        file_name,
        ['\n\n', '\n'],
        ['after', 'after'],
        1000,
        0,
        excel_rule=ExcelRule(),
        no_summary=True
    )
    return knowledge_imp.KnowledgeUtils.chunk2promt(''.join(raw_texts), {'source': file_name})


async def _initialize_chat(data: APIChatCompletion, login_user: UserPayload):
    """Initializes chat session, message, and LLM."""
    wsConfig = await WorkStationService.aget_config()

    model_info = next((m for m in wsConfig.models if m.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")

    conversationId = data.conversationId
    is_new_conversation = False
    if not conversationId:
        is_new_conversation = True
        conversationId = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversationId,
                flow_id='',
                flow_name='New Chat',
                flow_type=FlowType.WORKSTATION.value,
                user_id=login_user.user_id,
            ))

        # Telemetry for new session
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversationId,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source="platform",
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT
            ))

    conversation = await MessageSessionDao.async_get_one(conversationId)
    if conversation is None:
        raise ConversationNotFoundError()

    if data.overrideParentMessageId:
        message = await ChatMessageDao.aget_message_by_id(int(data.overrideParentMessageId))
    else:
        message = await ChatMessageDao.ainsert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversationId,
                flow_id='',
                type='human',
                is_bot=False,
                sender='User',
                files=json.dumps(data.files) if data.files else None,
                extra=json.dumps({'parentMessageId': data.parentMessageId}),
                message=data.text,
                category='question',
                source=0,
            ))

    bishengllm = await LLMService.get_bisheng_llm(
        model_id=data.model,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=login_user.user_id)

    return wsConfig, conversation, message, bishengllm, model_info, is_new_conversation


async def _log_telemetry_events(user_id: str, conversation_id: str, start_time: float):
    """Logs telemetry events for application alive and process."""
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)

    common_data = {
        "app_id": ApplicationTypeEnum.DAILY_CHAT.value,
        "app_name": ApplicationTypeEnum.DAILY_CHAT.value,
        "app_type": ApplicationTypeEnum.DAILY_CHAT,
        "chat_id": conversation_id,
        "start_time": int(start_time),
        "end_time": int(end_time),
    }

    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
        trace_id=trace_id_var.get(),
        event_data=ApplicationAliveEventData(**common_data)
    )

    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
        trace_id=trace_id_var.get(),
        event_data=ApplicationProcessEventData(**common_data, process_time=duration_ms)
    )


@router.post('/chat/completions')
async def chat_completions(
        request: Request,
        data: APIChatCompletion,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    start_time = time.time()
    try:
        wsConfig, conversation, message, bishengllm, model_info, is_new_conv = await _initialize_chat(data, login_user)
        conversationId = conversation.chat_id
        conversation_id_for_telemetry = conversationId
    except (BaseErrorCode, ValueError) as e:
        error_response = e if isinstance(e, BaseErrorCode) else ServerError(message=str(e))
        return EventSourceResponse(iter([error_response.to_sse_event_instance()]))
    except Exception as e:
        logger.exception(f'Error in chat completions setup: {e}')
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))

    def _build_final_content_for_db(final_res, reasoning_res, web_list):
        if reasoning_res:
            final_res = ''':::thinking\n''' + reasoning_res + '''\n:::''' + final_res
        if web_list:
            final_res = ''':::web\n''' + json.dumps(web_list, ensure_ascii=False) + '''\n:::''' + final_res
        return final_res

    async def event_stream():
        yield user_message(message.id, conversationId, 'User', data.text)

        prompt = data.text
        web_list = []
        error = False
        final_res = ''  # Accumulates the final response for the user
        reasoning_res = ''  # Accumulates the reasoning process
        max_token = wsConfig.maxTokens
        runId = uuid4().hex
        index = 0
        stepId = None
        source_document = None
        image_bases64 = []
        try:
            # Prepare prompt based on different modes (search, knowledge base, files)
            if data.search_enabled:
                stepId = f'step_${uuid4().hex}'
                yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
                index += 1

                search_decision_prompt = promptSearch % data.text
                searchRes = await bishengllm.ainvoke(search_decision_prompt)

                if searchRes.content == '1':
                    logger.info(f'Web search needed for prompt: {data.text}')
                    search_res, web_list = await webSearch(data.text, user_id=login_user.user_id)
                    content = {'content': [{'type': 'search_result', 'search_result': web_list}]}
                    yield SSEResponse(event='on_search_result',
                                      data=delta(id=stepId, delta=content)).toString()
                    prompt = wsConfig.webSearch.prompt.format(
                        search_results=search_res[:max_token],
                        cur_date=datetime.now().strftime('%Y-%m-%d'),
                        question=data.text)

            elif data.use_knowledge_base and (data.use_knowledge_base.personal_knowledge_enabled or len(
                    data.use_knowledge_base.organization_knowledge_ids) > 0):
                logger.info(f'Using knowledge base for prompt: {data.text}')
                chunks, source_document = await WorkStationService.queryChunksFromDB(data.text,
                                                                                     use_knowledge_param=data.use_knowledge_base,
                                                                                     max_token=max_token,
                                                                                     login_user=login_user)
                context_str = '\n'.join(chunks)
                if wsConfig.knowledgeBase.prompt:
                    prompt = wsConfig.knowledgeBase.prompt.format(retrieved_file_content=context_str,
                                                                  question=data.text)
                else:
                    prompt_service = await get_prompt_manager()
                    prompt = prompt_service.render_prompt('workstation', 'personal_knowledge',
                                                          retrieved_file_content=context_str,
                                                          question=data.text).prompt
                logger.debug(f'Knowledge prompt: {prompt}')


            elif data.files:

                logger.info(f'Using file content for prompt.')

                download_tasks = [async_file_download(file.get('filepath')) for file in data.files]

                downloaded_files = await asyncio.gather(*download_tasks)

                visual_tasks = []

                doc_tasks = []

                # image to base64
                async def _read_image_sync(filepath: str, filename: str) -> str:
                    async with aiofiles.open(filepath, mode='rb') as f:
                        image_data = await f.read()
                        ext = filename.split('.')[-1].lower()

                        mime_type = 'jpeg' if ext == 'jpg' else ext

                        return f"data:image/{mime_type};base64," + base64.b64encode(image_data).decode('utf-8')

                for filepath, filename in downloaded_files:

                    file_ext = filename.split('.')[-1].lower()

                    # Determine task type based on file extension and model capabilities
                    if model_info.visual and file_ext in visual_model_file_types:
                        # Image processing task
                        visual_tasks.append(_read_image_sync(filepath=filepath, filename=filename))

                    else:
                        # Document processing task
                        doc_tasks.append(
                            getFileContent(filepath_local=filepath,
                                           file_name=filename,
                                           invoke_user_id=login_user.user_id)
                        )

                # Execute all tasks concurrently
                results = await asyncio.gather(
                    asyncio.gather(*visual_tasks),
                    asyncio.gather(*doc_tasks)
                )

                # results[0] is image base64 list
                # results[1] is document content list
                image_bases64.extend(results[0])
                file_contents = results[1]

                file_context = '\n'.join(file_contents)[:max_token]
                prompt = wsConfig.fileUpload.prompt.format(file_content=file_context, question=data.text)

            # Update message with the generated prompt if it changed
            if prompt != data.text:
                extra = json.loads(message.extra) if message.extra else {}
                extra['prompt'] = prompt
                message.extra = json.dumps(extra, ensure_ascii=False)
                await ChatMessageDao.ainsert_one(message)

            # Prepare message history and call LLM
            history_messages = (await WorkStationService.get_chat_history(conversationId, 8))[:-1]
            content = [
                {'type': 'text', 'text': prompt},
            ]

            for img_base64 in image_bases64:
                content.append({'type': 'image_url', 'image_url': {
                    'url': img_base64
                }})

            inputs = [*history_messages, HumanMessage(content=content)]
            if wsConfig.systemPrompt:
                system_content = wsConfig.systemPrompt.format(cur_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                inputs.insert(0, SystemMessage(content=system_content))

            if not stepId:
                stepId = 'step_' + uuid4().hex
                yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
                index += 1

            # Stream LLM response
            async for chunk in bishengllm.astream(inputs):
                content = chunk.content
                reasoning_content = chunk.additional_kwargs.get('reasoning_content', '')

                if content:
                    final_res += content
                    yield SSEResponse(event='on_message_delta',
                                      data=delta(id=stepId,
                                                 delta={'content': [{'type': 'text', 'text': content}]})).toString()
                if reasoning_content:
                    reasoning_res += reasoning_content
                    yield SSEResponse(event='on_reasoning_delta',
                                      data=delta(id=stepId, delta={
                                          'content': [{'type': 'think', 'think': reasoning_content}]})).toString()

            final_content_for_db = _build_final_content_for_db(final_res, reasoning_res, web_list)

        except BaseErrorCode as e:
            error = True
            final_content_for_db = json.dumps(e.to_dict())
            yield e.to_sse_event_instance_str()
        except Exception as e:
            error = True
            server_error = ServerError(exception=e)
            logger.exception(f'Error in processing the prompt')
            final_content_for_db = json.dumps(server_error.to_dict())
            yield server_error.to_sse_event_instance_str()

        # Send final message and generate title if needed
        yield await final_message(conversation, conversation.flow_name, message, final_content_for_db,
                                  error, model_info.displayName, source_document)

        if is_new_conv:
            asyncio.create_task(
                genTitle(data.text, final_content_for_db, bishengllm, conversationId, login_user, request))

    try:
        return StreamingResponse(event_stream(), media_type='text/event-stream')
    finally:
        await _log_telemetry_events(login_user.user_id, conversation_id_for_telemetry, start_time)


@router.get('/app/frequently_used')
def frequently_used_chat(login_user: UserPayload = Depends(UserPayload.get_login_user),
                         user_link_type: Optional[str] = 'app',
                         page: Optional[int] = 1,
                         limit: Optional[int] = 8
                         ):
    data, _ = WorkFlowService.get_frequently_used_flows(login_user, user_link_type, page, limit)

    return resp_200(data=data)


@router.post('/app/frequently_used')
def frequently_used_chat(login_user: UserPayload = Depends(UserPayload.get_login_user),
                         data: FrequentlyUsedChat = Body(..., description='Add your favorite apps')
                         ):
    is_new = WorkFlowService.add_frequently_used_flows(login_user, data.user_link_type, data.type_detail)
    if is_new:
        return resp_200(message='Added')
    else:
        return AgentAlreadyExistsError.return_resp()


@router.delete('/app/frequently_used')
def frequently_used_chat(login_user: UserPayload = Depends(UserPayload.get_login_user),
                         user_link_type: Optional[str] = None,
                         type_detail: Optional[str] = None
                         ):
    WorkFlowService.delete_frequently_used_flows(login_user, user_link_type, type_detail)
    return resp_200(message='Delete successful')


@router.get('/app/uncategorized')
def get_uncategorized_chat(login_user: UserPayload = Depends(UserPayload.get_login_user),
                           page: Optional[int] = 1,
                           limit: Optional[int] = 8):
    data, _ = WorkFlowService.get_uncategorized_flows(login_user, page, limit)
    return resp_200(data=data)
