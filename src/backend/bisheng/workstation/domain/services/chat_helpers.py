import asyncio
import base64
import json
from datetime import datetime
from typing import List

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
                    response_message
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


# --------------------------------------------------------------------------- #
# v2.5 Agent 模式 ChatResponse 工具函数
#
# 旧数据 (category='question'/'answer' 且 message 为纯文本) 在读取层通过
# `_is_new_format` / `_format_new_message` / `_convert_legacy_message` 判别转换,
# DB 不做数据迁移.
# --------------------------------------------------------------------------- #

import re  # noqa: E402  (re is only needed by legacy-format parser)


def _sse_resp(
        category: str,
        type_: str,
        message,
        chat_id: str,
        message_id=None,
        is_bot: bool = True,
        flow_id: str = '',
        citations=None,
) -> str:
    """Build an SSE event string in ChatResponse format.

    The payload shape mirrors bisheng.api.v1.schemas.ChatResponse so the
    workflow frontend renderer can be shared. `type_` is passed as string
    to avoid colliding with Python builtin `type`.
    """
    resp = {
        'category': category,
        'type': type_,
        'message': message,
        'is_bot': is_bot,
        'chat_id': chat_id,
        'flow_id': flow_id,
    }
    if message_id is not None:
        resp['message_id'] = message_id
    if citations is not None:
        resp['citations'] = citations
    return f'event: message\ndata: {json.dumps(resp, ensure_ascii=False, default=custom_json_serializer)}\n\n'


def _is_new_format(msg: ChatMessage) -> bool:
    """Return True when `msg.message` is already the new JSON object format.

    New format signatures:
      - category in ('agent_answer','agent_tool_call','agent_thinking') and message parses to dict
      - category == 'question' and message parses to dict with 'query' key
    """
    if not msg or not msg.message:
        return False
    if msg.category in ('agent_answer', 'agent_tool_call', 'agent_thinking'):
        try:
            parsed = json.loads(msg.message)
            return isinstance(parsed, dict)
        except (json.JSONDecodeError, TypeError):
            return False
    if msg.category == 'question':
        try:
            parsed = json.loads(msg.message)
            return isinstance(parsed, dict) and 'query' in parsed
        except (json.JSONDecodeError, TypeError):
            return False
    return False


def _message_base_fields(msg: ChatMessage) -> dict:
    return {
        'message_id': msg.id,
        'is_bot': msg.is_bot,
        'files': json.loads(msg.files) if msg.files else [],
        'user_id': msg.user_id,
        'chat_id': msg.chat_id,
        'flow_id': msg.flow_id,
        'source': msg.source,
        'sender': msg.sender,
        'create_time': msg.create_time.isoformat() if msg.create_time else None,
    }


def _normalise_agent_message_content(content: dict) -> dict:
    """Coerce a persisted agent_answer payload into the unified
    `{msg, events}` shape. Handles three shapes the DB may hold:

      (a) New unified         — already has `events`. Pass through (keep msg).
      (b) Modern legacy       — has `steps` + `thinking_segments` + `tool_calls`.
                                Walk steps in order; pull matching segment / tool.
      (c) Oldest legacy       — has `reasoning_content` (string) + maybe `tool_calls`.
                                Emit one thinking event followed by tool_calls.
    """
    if not isinstance(content, dict):
        return content
    if 'events' in content and isinstance(content.get('events'), list):
        return {'msg': content.get('msg', ''), 'events': content['events']}

    steps = content.get('steps') or []
    segments = content.get('thinking_segments') or []
    tool_calls = content.get('tool_calls') or []
    reasoning = content.get('reasoning_content') or ''
    events: list[dict] = []

    if isinstance(steps, list) and steps:
        seg_by_idx = {s.get('segment_idx'): s for s in segments if isinstance(s, dict)}
        tc_by_id = {t.get('tool_call_id'): t for t in tool_calls if isinstance(t, dict)}
        seg_iter = iter(s for s in segments if isinstance(s, dict))
        tc_iter = iter(t for t in tool_calls if isinstance(t, dict))
        for step in steps:
            if not isinstance(step, dict):
                continue
            stype = step.get('type')
            if stype == 'thinking':
                seg = seg_by_idx.get(step.get('segment_idx')) or next(seg_iter, None)
                if seg:
                    events.append({
                        'type': 'thinking',
                        'content': seg.get('content', '') or '',
                        'duration_ms': seg.get('duration_ms'),
                    })
                elif reasoning:
                    events.append({
                        'type': 'thinking',
                        'content': reasoning,
                        'duration_ms': step.get('duration_ms'),
                    })
            elif stype == 'tool_call':
                tc = tc_by_id.get(step.get('tool_call_id')) or next(tc_iter, None)
                if tc:
                    events.append({'type': 'tool_call', **tc})
    else:
        if reasoning:
            events.append({'type': 'thinking', 'content': str(reasoning)})
        for tc in tool_calls:
            if isinstance(tc, dict):
                events.append({'type': 'tool_call', **tc})

    return {'msg': content.get('msg', ''), 'events': events}


def _format_new_message(msg: ChatMessage) -> dict:
    """Format a ChatMessage that is already in the new JSON format."""
    try:
        message_content = json.loads(msg.message) if msg.message else ''
    except (json.JSONDecodeError, TypeError):
        message_content = msg.message or ''
    if msg.category == 'agent_answer' and isinstance(message_content, dict):
        message_content = _normalise_agent_message_content(message_content)
    return {
        **_message_base_fields(msg),
        'message': message_content,
        'category': msg.category,
        'type': msg.type or 'end',
    }


_LEGACY_THINKING_RE = re.compile(r':::thinking\n([\s\S]*?)\n:::')
_LEGACY_WEB_RE = re.compile(r':::web\n([\s\S]*?)\n:::')


def _convert_legacy_message(msg: ChatMessage) -> dict:
    """Convert a legacy-format ChatMessage (plain text + `:::thinking`/`:::web`
    markers, or a plain `question` string) into the new JSON-shaped dict.

    The conversion happens only at read time, no DB mutation.
    """
    base = _message_base_fields(msg)

    if msg.category == 'question':
        # Legacy `question` rows: message is plain text, extras may contain parentMessageId.
        return {
            **base,
            'message': {'query': msg.message or '', 'files': base['files']},
            'category': 'question',
            'type': 'over',
        }

    if msg.category == 'answer':
        text = msg.message or ''
        reasoning = ''
        tool_calls: list[dict] = []

        thinking = _LEGACY_THINKING_RE.search(text)
        if thinking:
            reasoning = thinking.group(1)
            text = text.replace(thinking.group(0), '')

        web = _LEGACY_WEB_RE.search(text)
        if web:
            try:
                web_data = json.loads(web.group(1))
            except (json.JSONDecodeError, TypeError):
                web_data = []
            tool_calls.append({
                'tool_call_id': f'legacy_{msg.id}',
                'tool_name': 'web_search',
                'display_name': 'web_search',
                'tool_type': 'web',
                'results': web_data,
                'error': None,
            })
            text = text.replace(web.group(0), '')

        events: list[dict] = []
        if reasoning:
            events.append({'type': 'thinking', 'content': reasoning})
        for tc in tool_calls:
            events.append({'type': 'tool_call', **tc})

        return {
            **base,
            'message': {'msg': text.strip(), 'events': events},
            'category': 'agent_answer',
            'type': 'end',
        }

    # Other categories (processing / error / etc.) — pass through as string.
    return {
        **base,
        'message': msg.message or '',
        'category': msg.category,
        'type': msg.type or 'over',
    }


def _drop_legacy_sibling_branches(messages: list[ChatMessage]) -> list[ChatMessage]:
    """v2.5 / R10: same-question regenerate branches collapse to latest only.

    Legacy tree answers all share the same `parentMessageId` under one question.
    We keep only the row with max `create_time` per `parentMessageId`, dropping
    the older siblings. New-format messages (category `agent_answer`, no
    parentMessageId in `extra`) pass through untouched.
    """
    if not messages:
        return messages

    latest_per_parent: dict[str, ChatMessage] = {}
    drop_ids: set = set()

    for msg in messages:
        if msg.category != 'answer':
            continue
        try:
            extra = json.loads(msg.extra) if msg.extra else {}
        except (json.JSONDecodeError, TypeError):
            extra = {}
        pid = extra.get('parentMessageId')
        if pid in (None, '', 0):
            continue
        pid_key = str(pid)
        prev = latest_per_parent.get(pid_key)
        if prev is None:
            latest_per_parent[pid_key] = msg
            continue
        # Pick the more recent one; ties → larger id wins (deterministic).
        prev_key = (prev.create_time or datetime.min, prev.id or 0)
        curr_key = (msg.create_time or datetime.min, msg.id or 0)
        if curr_key > prev_key:
            drop_ids.add(prev.id)
            latest_per_parent[pid_key] = msg
        else:
            drop_ids.add(msg.id)

    if not drop_ids:
        return messages
    return [m for m in messages if m.id not in drop_ids]
