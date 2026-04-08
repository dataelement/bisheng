import asyncio
import base64
import json
from datetime import datetime
from typing import List
from uuid import uuid4

import aiofiles
from fastapi import Request
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.chat.utils import SourceType, process_source_document
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.utils.title_generator import generate_conversation_title_async
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


async def final_message(
    conversation: MessageSession,
    title: str,
    request_message: ChatMessage,
    text: str,
    error: bool,
    model_name: str,
    source_document: List[Document] = None,
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
                    citations=None,
                )
            ).model_dump(),
        },
        default=custom_json_serializer,
    )
    return f'event: message\ndata: {msg}\n\n'


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
