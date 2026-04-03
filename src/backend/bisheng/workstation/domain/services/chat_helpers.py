import asyncio
import base64
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiofiles
from fastapi import Request
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.v1.schema.chat_schema import SSEResponse, delta
from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.chat.utils import SourceType, process_source_document
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.database import get_async_db_session
from bisheng.common.utils.title_generator import generate_conversation_title_async
from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationRegistrySSEPayload,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.utils import get_request_ip
from bisheng.workstation.domain.schemas import WorkstationConversation, WorkstationMessage


def custom_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f'Type {type(obj)} not serializable')


def user_message(msg_id, conversation_id, sender, text):
    msg = json.dumps({
        'message': {
            'messageId': msg_id,
            'conversationId': conversation_id,
            'sender': sender,
            'text': text,
        },
        'created': True,
    })
    return f'event: message\ndata: {msg}\n\n'


def step_message(step_id, run_id, index, msg_id):
    msg = json.dumps({
        'event': 'on_run_step',
        'data': {
            'id': step_id,
            'runId': run_id,
            'type': 'message_creation',
            'index': index,
            'stepDetails': {
                'type': 'message_creation',
                'message_creation': {'message_id': msg_id},
            },
        },
    })
    return f'event: message\ndata: {msg}\n\n'


def citation_registry_message(message_id: str, items: List[CitationRegistryItemSchema]) -> str:
    payload = CitationRegistrySSEPayload(messageId=message_id, items=items).model_dump(mode='json')
    return SSEResponse(
        event='on_citation_registry',
        data=delta(id=message_id, delta=payload),
    ).toString()


async def persist_citation_registry(
    message_id: int,
    chat_id: str,
    flow_id: str,
    citation_registry: Optional[List[CitationRegistryItemSchema]],
) -> List[CitationRegistryItemSchema]:
    """Persist normalized citation registry items for a message."""
    if not citation_registry or message_id is None:
        return []

    try:
        async with get_async_db_session() as session:
            repository = MessageCitationRepositoryImpl(session)
            registry_service = CitationRegistryService(repository)
            saved_entities = await registry_service.save_citations(
                message_id=message_id,
                items=citation_registry,
                chat_id=chat_id,
                flow_id=flow_id,
            )
            return [registry_service.to_registry_item(entity) for entity in saved_entities]
    except Exception as exc:
        logger.exception(
            'persist_citation_registry failed message_id={} chat_id={} flow_id={}: {}',
            message_id,
            chat_id,
            flow_id,
            exc,
        )
        return []


def build_web_search_display_items(
    web_results: List[Dict[str, Any]],
    items: List[CitationRegistryItemSchema],
) -> List[dict]:
    """Build front-end search result items aligned with citation registry semantics."""
    search_results: List[dict] = []
    for web_result, item in zip(web_results, items):
        payload = WebCitationPayloadSchema.model_validate(item.sourcePayload)
        search_results.append({
            'citationId': item.citationId,
            'type': item.type.value,
            'groupKey': item.groupKey,
            'displayOrder': item.displayOrder,
            'id': web_result.get('id'),
            'title': payload.title,
            'snippet': payload.snippet,
            'url': payload.url,
            'source': payload.source,
            'siteIcon': payload.siteIcon,
            'datePublished': payload.datePublished,
        })
    return search_results


async def final_message(
    conversation: MessageSession,
    title: str,
    request_message: ChatMessage,
    text: str,
    error: bool,
    model_name: str,
    source_document: List[Document] = None,
    citation_registry: Optional[List[CitationRegistryItemSchema]] = None,
):
    response_message = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id='',
            type='assistant',
            is_bot=True,
            message=text,
            category='answer',
            sender=model_name,
            extra=json.dumps({'parentMessageId': request_message.id, 'error': error}),
            source=SourceType.FILE.value if source_document else SourceType.NOT_SUPPORT.value,
        )
    )
    if citation_registry is None and source_document:
        citation_registry = CitationRegistryService.build_rag_registry(source_document)

    citation_event = ''
    persisted_citations: List[CitationRegistryItemSchema] = []
    if citation_registry:
        persisted_citations = await persist_citation_registry(
            message_id=response_message.id,
            chat_id=conversation.chat_id,
            flow_id=conversation.flow_id or '',
            citation_registry=citation_registry,
        )
        if persisted_citations:
            citation_event = citation_registry_message(
                message_id=str(response_message.id),
                items=persisted_citations,
            )

    if source_document:
        asyncio.create_task(
            process_source_document(
                source_document=source_document,
                chat_id=conversation.chat_id,
                message_id=response_message.id,
                answer=text,
            )
        )

    msg = json.dumps(
        {
            'final': True,
            'conversation': WorkstationConversation.from_chat_session(conversation).model_dump(),
            'title': title,
            'requestMessage': (await WorkstationMessage.from_chat_message(request_message)).model_dump(),
            'responseMessage': (
                await WorkstationMessage.from_chat_message(
                    response_message,
                    citations=persisted_citations or None,
                )
            ).model_dump(),
        },
        default=custom_json_serializer,
    )
    return f'{citation_event}event: message\ndata: {msg}\n\n'


async def gen_title(
    human: str,
    assistant: str,
    llm: BaseChatModel,
    conversation_id: str,
    login_user: UserPayload,
    request: Request,
):
    title = await generate_conversation_title_async(question=human, answer=assistant, llm=llm)
    session = await MessageSessionDao.async_get_one(conversation_id)
    if session:
        await MessageSessionDao.update_session_name(chat_id=session.chat_id, name=title)
        await AuditLogService.create_chat_message(
            user=login_user,
            ip_address=get_request_ip(request),
            message=session,
        )


async def read_image_as_data_url(filepath: str, filename: str) -> str:
    async with aiofiles.open(filepath, mode='rb') as file_obj:
        image_data = await file_obj.read()
        ext = filename.split('.')[-1].lower()
        mime_type = 'jpeg' if ext == 'jpg' else ext
        return f'data:image/{mime_type};base64,' + base64.b64encode(image_data).decode('utf-8')


def build_final_content_for_db(final_res, reasoning_res, web_list):
    if reasoning_res:
        final_res = ':::thinking\n' + reasoning_res + '\n:::' + final_res
    if web_list:
        final_res = ':::web\n' + json.dumps(web_list, ensure_ascii=False) + '\n:::' + final_res
    return final_res


def build_step_id() -> str:
    return f'step_{uuid4().hex}'
