import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from fastapi import Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sse_starlette import EventSourceResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, SSEResponse, delta
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.errcode.workstation import ConversationNotFoundError, WebSearchToolNotFoundError
from bisheng.common.schemas.telemetry.event_data_schema import (
    ApplicationAliveEventData,
    ApplicationProcessEventData,
    NewMessageSessionEventData,
)
from bisheng.common.services import telemetry_service
from bisheng.core.cache.utils import async_file_download
from bisheng.core.logger import trace_id_var
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor

from .constants import PROMPT_SEARCH, VISUAL_MODEL_FILE_TYPES
from .chat_helpers import (
    build_final_content_for_db,
    build_web_search_display_items,
    build_step_id,
    final_message,
    gen_title,
    read_image_as_data_url,
    step_message,
    user_message,
)
from .workstation_service import WorkStationService


async def web_search(query: str, user_id: int) -> Tuple[str, List[Dict[str, Any]], List[CitationRegistryItemSchema], List[Dict[str, Any]]]:
    """Search the web via configured tool."""
    web_search_info = GptsToolsDao.get_tool_by_tool_key('web_search')
    if not web_search_info:
        raise WebSearchToolNotFoundError(exception=Exception('No web_search tool found in database'))
    web_search_tool = await ToolExecutor.init_by_tool_id(
        web_search_info.id,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=user_id,
    )
    if not web_search_tool:
        raise WebSearchToolNotFoundError(exception=Exception('No web_search tool found in gpts tools'))
    web_results = await web_search_tool.ainvoke(input={'query': query})
    web_results = json.loads(web_results)
    citation_registry = CitationRegistryService.build_web_registry(web_results)
    search_result_items = build_web_search_display_items(web_results, citation_registry)
    # TODO: Build citation-aware prompt context in the workstation web search business layer.
    search_res = '\n\n'.join(
        '\n'.join(
            str(item)
            for item in (
                result.get('title') or result.get('name') or result.get('url'),
                result.get('url') or result.get('link'),
                result.get('snippet') or result.get('summary') or result.get('content'),
            )
            if item
        )
        for result in web_results
    )
    return search_res, web_results, citation_registry, search_result_items


async def get_file_content(filepath_local: str, file_name: str, invoke_user_id: int):
    """Extract uploaded file content for prompt building."""
    from bisheng.api.v1.schemas import FileProcessBase
    from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

    file_rule = FileProcessBase(
        knowledge_id=0,
        separator=['\n\n', '\n'],
        separator_rule=['after', 'after'],
        chunk_size=1000,
        chunk_overlap=0,
    )
    pipeline = TempFilePipeline(
        invoke_user_id=invoke_user_id,
        local_file_path=filepath_local,
        file_name=file_name,
        file_rule=file_rule,
    )
    try:
        result = await pipeline.arun()
        raw_texts = [doc.page_content for doc in result.documents]
    except KnowledgeFileNotSupportedError:
        raw_texts = []
    return knowledge_imp.KnowledgeUtils.chunk2promt(''.join(raw_texts), {'source': file_name})


async def initialize_chat(data: APIChatCompletion, login_user: UserPayload):
    """Initialize chat session, message, and llm."""
    ws_config = await WorkStationService.aget_config()
    model_info = next((model for model in ws_config.models if model.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")

    conversation_id = data.conversationId
    is_new_conversation = False
    if not conversation_id:
        is_new_conversation = True
        conversation_id = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversation_id,
                name='New Chat',
                flow_type=FlowType.WORKSTATION.value,
                user_id=login_user.user_id,
            )
        )
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversation_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source='platform',
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT,
            ),
        )

    conversation = await MessageSessionDao.async_get_one(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    if data.overrideParentMessageId:
        message = await ChatMessageDao.aget_message_by_id(int(data.overrideParentMessageId))
    else:
        message = await ChatMessageDao.ainsert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversation_id,
                flow_id='',
                type='human',
                is_bot=False,
                sender='User',
                files=json.dumps(data.files) if data.files else None,
                extra=json.dumps({'parentMessageId': data.parentMessageId}),
                message=data.text,
                category='question',
                source=0,
            )
        )

    bisheng_llm = await LLMService.get_bisheng_llm(
        model_id=data.model,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=login_user.user_id,
    )
    return ws_config, conversation, message, bisheng_llm, model_info, is_new_conversation


async def log_telemetry_events(user_id: str, conversation_id: str, start_time: float):
    """Log application alive and duration telemetry."""
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)
    common_data = {
        'app_id': ApplicationTypeEnum.DAILY_CHAT.value,
        'app_name': ApplicationTypeEnum.DAILY_CHAT.value,
        'app_type': ApplicationTypeEnum.DAILY_CHAT,
        'chat_id': conversation_id,
        'start_time': int(start_time),
        'end_time': int(end_time),
    }
    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
        trace_id=trace_id_var.get(),
        event_data=ApplicationAliveEventData(**common_data),
    )
    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
        trace_id=trace_id_var.get(),
        event_data=ApplicationProcessEventData(**common_data, process_time=duration_ms),
    )


async def stream_chat_completion(request: Request, data: APIChatCompletion, login_user: UserPayload):
    """Handle workstation chat completion stream."""
    start_time = time.time()
    try:
        ws_config, conversation, message, bisheng_llm, model_info, is_new_conv = await initialize_chat(data, login_user)
        conversation_id = conversation.chat_id
        conversation_id_for_telemetry = conversation_id
    except (BaseErrorCode, ValueError) as exc:
        error_response = exc if isinstance(exc, BaseErrorCode) else ServerError(message=str(exc))
        return EventSourceResponse(iter([error_response.to_sse_event_instance()]))
    except Exception as exc:
        logger.exception(f'Error in chat completions setup: {exc}')
        return EventSourceResponse(iter([ServerError(exception=exc).to_sse_event_instance()]))

    async def event_stream():
        yield user_message(message.id, conversation_id, 'User', data.text)

        prompt = data.text
        web_list = []
        citation_registry = None
        error = False
        final_res = ''
        reasoning_res = ''
        max_token = ws_config.maxTokens
        run_id = uuid4().hex
        index = 0
        step_id = None
        source_document = None
        image_bases64 = []
        try:
            if data.search_enabled:
                step_id = build_step_id()
                yield step_message(step_id, run_id, index, f'msg_{uuid4().hex}')
                index += 1

                search_decision_prompt = PROMPT_SEARCH % data.text
                search_res = await bisheng_llm.ainvoke(search_decision_prompt)
                if search_res.content == '1':
                    logger.info(f'Web search needed for prompt: {data.text}')
                    search_text, web_list, citation_registry, search_result_items = await web_search(
                        data.text,
                        user_id=login_user.user_id,
                    )
                    content = {'content': [{'type': 'search_result', 'search_result': search_result_items}]}
                    yield SSEResponse(
                        event='on_search_result',
                        data=delta(id=step_id, delta=content),
                    ).toString()
                    prompt = ws_config.webSearch.prompt.format(
                        search_results=search_text[:max_token],
                        cur_date=datetime.now().strftime('%Y-%m-%d'),
                        question=data.text,
                    )
            elif data.use_knowledge_base and (
                len(data.use_knowledge_base.knowledge_space_ids) > 0
                or len(data.use_knowledge_base.organization_knowledge_ids) > 0
            ):
                logger.info(f'Using knowledge base for prompt: {data.text}')
                chunks, source_document, citation_registry = await WorkStationService.queryChunksFromDB(
                    data.text,
                    use_knowledge_param=data.use_knowledge_base,
                    max_token=max_token,
                    login_user=login_user,
                )
                context_str = '\n'.join(chunks)
                if ws_config.knowledgeBase.prompt:
                    prompt = ws_config.knowledgeBase.prompt.format(
                        retrieved_file_content=context_str,
                        question=data.text,
                    )
                else:
                    prompt_service = await get_prompt_manager()
                    prompt = prompt_service.render_prompt(
                        'workstation',
                        'personal_knowledge',
                        retrieved_file_content=context_str,
                        question=data.text,
                    ).prompt
                logger.debug(f'Knowledge prompt: {prompt}')
            elif data.files:
                logger.info('Using file content for prompt.')
                download_tasks = [async_file_download(file.get('filepath')) for file in data.files]
                downloaded_files = await asyncio.gather(*download_tasks)

                visual_tasks = []
                doc_tasks = []
                for filepath, filename in downloaded_files:
                    file_ext = filename.split('.')[-1].lower()
                    if model_info.visual and file_ext in VISUAL_MODEL_FILE_TYPES:
                        visual_tasks.append(read_image_as_data_url(filepath=filepath, filename=filename))
                    else:
                        doc_tasks.append(
                            get_file_content(
                                filepath_local=filepath,
                                file_name=filename,
                                invoke_user_id=login_user.user_id,
                            )
                        )

                visual_results, doc_results = await asyncio.gather(
                    asyncio.gather(*visual_tasks),
                    asyncio.gather(*doc_tasks),
                )
                image_bases64.extend(visual_results)
                file_context = '\n'.join(doc_results)[:max_token]
                prompt = ws_config.fileUpload.prompt.format(file_content=file_context, question=data.text)

            if prompt != data.text:
                extra = json.loads(message.extra) if message.extra else {}
                extra['prompt'] = prompt
                message.extra = json.dumps(extra, ensure_ascii=False)
                await ChatMessageDao.ainsert_one(message)

            history_messages = (await WorkStationService.get_chat_history(conversation_id, 8))[:-1]
            content = [{'type': 'text', 'text': prompt}]
            for img_base64 in image_bases64:
                content.append({'type': 'image_url', 'image_url': {'url': img_base64}})
            if not image_bases64:
                content = prompt

            inputs = [*history_messages, HumanMessage(content=content)]
            if ws_config.systemPrompt:
                system_content = ws_config.systemPrompt.format(
                    cur_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
                inputs.insert(0, SystemMessage(content=system_content))

            if not step_id:
                step_id = build_step_id()
                yield step_message(step_id, run_id, index, f'msg_{uuid4().hex}')
                index += 1

            async for chunk in bisheng_llm.astream(inputs):
                content = chunk.content
                reasoning_content = chunk.additional_kwargs.get('reasoning_content', '')
                if content:
                    final_res += content
                    yield SSEResponse(
                        event='on_message_delta',
                        data=delta(id=step_id, delta={'content': [{'type': 'text', 'text': content}]}),
                    ).toString()
                if reasoning_content:
                    reasoning_res += reasoning_content
                    yield SSEResponse(
                        event='on_reasoning_delta',
                        data=delta(
                            id=step_id,
                            delta={'content': [{'type': 'think', 'think': reasoning_content}]},
                        ),
                    ).toString()

            final_content_for_db = build_final_content_for_db(final_res, reasoning_res, web_list)
        except BaseErrorCode as exc:
            error = True
            final_content_for_db = json.dumps(exc.to_dict())
            yield exc.to_sse_event_instance_str()
        except Exception as exc:
            error = True
            server_error = ServerError(exception=exc)
            logger.exception('Error in processing the prompt')
            final_content_for_db = json.dumps(server_error.to_dict())
            yield server_error.to_sse_event_instance_str()

        yield await final_message(
            conversation,
            conversation.name,
            message,
            final_content_for_db,
            error,
            model_info.displayName,
            source_document,
            citation_registry,
        )

        if is_new_conv:
            asyncio.create_task(
                gen_title(data.text, final_content_for_db, bisheng_llm, conversation_id, login_user, request)
            )

    try:
        return StreamingResponse(event_stream(), media_type='text/event-stream')
    finally:
        await log_telemetry_events(str(login_user.user_id), conversation_id_for_telemetry, start_time)
