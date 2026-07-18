"""F028 T007 — unit tests for the conversation export service load/turn build.

Scope: ``ConversationExportService._load_and_validate_messages`` and
``ConversationExportService._build_turns`` are exercised in isolation; DAO
layers are monkeypatched. Subprocess-bound rendering is out of scope here —
it belongs to T009/T010.

AC coverage: AC-01, AC-06, AC-08, AC-09, AC-11, AC-14, AC-15, AC-25, AC-27, AC-28
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from bisheng.common.errcode.workstation import (
    ConversationMessageBatchTooLargeError,
    ConversationMessageNotFoundError,
    ConversationMessageNotOwnedError,
)
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.workstation.domain.services.conversation_export_service import (
    ConversationExportService,
    ConversationTurn,
)


# --- Fixtures --------------------------------------------------------------


def _make_chat_message(
    id_: int,
    category: str,
    content: str,
    *,
    chat_id: str = 'chat-1',
    user_id: int = 1,
    parent_msg_id: Optional[int] = None,
    sender: Optional[str] = None,
) -> ChatMessage:
    """Build a real ChatMessage instance via the full SQLModel constructor.

    Going through ``ChatMessage(...)`` (not model_construct) is required so
    SQLAlchemy's instrumented attribute descriptors (``_sa_instance_state``)
    are initialized; otherwise reading ``.id`` later raises AttributeError on
    ``self.impl.supports_population``.
    """
    extra_dict = {}
    if parent_msg_id is not None:
        extra_dict['parentMessageId'] = parent_msg_id
    return ChatMessage(
        id=id_,
        is_bot=(category != 'question'),
        chat_id=chat_id,
        user_id=user_id,
        flow_id='flow-1',
        type='human' if category == 'question' else 'assistant',
        category=category,
        message=content,
        sender=sender or '',
        extra=json.dumps(extra_dict) if extra_dict else None,
        tenant_id=1,
    )


def _make_session(
    *,
    chat_id: str = 'chat-1',
    flow_type: int = FlowType.WORKSTATION.value,
    user_id: int = 1,
    name: str = 'New Chat',
    flow_name: str = '',
) -> MessageSession:
    return MessageSession(
        chat_id=chat_id,
        flow_id='flow-1',
        flow_name=flow_name,
        flow_type=flow_type,
        user_id=user_id,
        name=name,
        tenant_id=1,
    )


@pytest.fixture
def patch_daos(monkeypatch: pytest.MonkeyPatch):
    """Yield a small registry that lets each test pre-load expected results.

    Calling ``patch_daos.set_session(session)`` makes
    ``MessageSessionDao.async_get_one`` resolve to that session for ANY chat_id;
    ``patch_daos.set_messages(rows)`` makes
    ``ChatMessageDao.aget_messages_by_ids`` resolve to that exact list.

    We replace the classmethods with module-level async functions wrapped in
    ``classmethod``; AsyncMock would also work but the explicit form keeps the
    arg-shape contract visible to the reader.
    """

    state: dict = {'session': None, 'messages': []}

    async def _fake_async_get_one(_cls, _chat_id):  # type: ignore[no-untyped-def]
        return state['session']

    async def _fake_aget_messages_by_ids(_cls, message_ids, user_id, chat_id):  # type: ignore[no-untyped-def]
        # Mimic the real DAO semantics: filter by user_id + chat_id + id IN.
        return [
            m for m in state['messages']
            if m.id in message_ids and m.user_id == user_id and m.chat_id == chat_id
        ]

    monkeypatch.setattr(MessageSessionDao, 'async_get_one', classmethod(_fake_async_get_one))
    monkeypatch.setattr(ChatMessageDao, 'aget_messages_by_ids', classmethod(_fake_aget_messages_by_ids))

    class _Registry:
        @staticmethod
        def set_session(s):
            state['session'] = s

        @staticmethod
        def set_messages(rows):
            state['messages'] = list(rows)

    return _Registry()


# --- _load_and_validate_messages tests -------------------------------------


async def test_load_happy_path(patch_daos):
    """AC-01: 同会话同用户的 5 条 message 按 id 拉回，session 同时返回。"""
    session = _make_session()
    messages = [
        _make_chat_message(1, 'question', '你好'),
        _make_chat_message(2, 'answer', '你好，有什么可以帮你？', parent_msg_id=1),
        _make_chat_message(3, 'question', '今天天气'),
        _make_chat_message(4, 'answer', '北京晴', parent_msg_id=3),
        _make_chat_message(5, 'answer', '北京多云', parent_msg_id=3),
    ]
    patch_daos.set_session(session)
    patch_daos.set_messages(messages)

    loaded, loaded_session = await ConversationExportService._load_and_validate_messages(
        chat_id='chat-1', message_ids=[1, 2, 3, 4, 5], user_id=1,
    )
    assert [m.id for m in loaded] == [1, 2, 3, 4, 5]
    assert loaded_session is session


async def test_load_cross_chat_rejected(patch_daos):
    """AC-28: message_ids 属于其它 chat_id — 全部被 SQL 过滤掉 → NotOwned (12062)。"""
    session = _make_session(chat_id='chat-1')
    messages = [
        _make_chat_message(10, 'question', '你好', chat_id='other-chat'),
    ]
    patch_daos.set_session(session)
    patch_daos.set_messages(messages)

    with pytest.raises(ConversationMessageNotOwnedError):
        await ConversationExportService._load_and_validate_messages(
            chat_id='chat-1', message_ids=[10], user_id=1,
        )


async def test_load_cross_user_rejected(patch_daos):
    """AC-25: message_ids 属于另一个 user — SQL 过滤为空 → NotOwned (12062)。"""
    session = _make_session(user_id=2)  # session 不属于当前用户
    patch_daos.set_session(session)
    patch_daos.set_messages([])

    with pytest.raises(ConversationMessageNotOwnedError):
        await ConversationExportService._load_and_validate_messages(
            chat_id='chat-1', message_ids=[1], user_id=1,
        )


async def test_load_partial_missing_rejected(patch_daos):
    """AC-27: 部分 id 不存在 → NotFound (12060) 含缺失 id 列表。"""
    session = _make_session()
    messages = [
        _make_chat_message(1, 'question', '你好'),
        # id=2 不存在
        _make_chat_message(3, 'question', 'q'),
    ]
    patch_daos.set_session(session)
    patch_daos.set_messages(messages)

    with pytest.raises(ConversationMessageNotFoundError) as exc:
        await ConversationExportService._load_and_validate_messages(
            chat_id='chat-1', message_ids=[1, 2, 3], user_id=1,
        )
    # Error message should mention the missing id for diagnostics
    assert '2' in str(exc.value)


async def test_load_over_200_rejected(patch_daos):
    """AC-08: 超过 200 条 → BatchTooLarge (12061), 在 DAO 调用之前 short-circuit。"""
    patch_daos.set_session(_make_session())
    patch_daos.set_messages([])  # should not even be queried

    with pytest.raises(ConversationMessageBatchTooLargeError):
        await ConversationExportService._load_and_validate_messages(
            chat_id='chat-1', message_ids=list(range(1, 202)), user_id=1,
        )


async def test_load_session_not_found(patch_daos):
    """AC-25/26 兜底: session 完全找不到 → NotOwned (12062), 不暴露具体原因。"""
    patch_daos.set_session(None)
    patch_daos.set_messages([])

    with pytest.raises(ConversationMessageNotOwnedError):
        await ConversationExportService._load_and_validate_messages(
            chat_id='ghost', message_ids=[1], user_id=1,
        )


# --- _build_turns tests ----------------------------------------------------


def test_build_turns_daily_mode():
    """AC-11: flow_type=15 (日常模式)，取 ChatMessage.sender 当模型名。"""
    session = _make_session(flow_type=FlowType.WORKSTATION.value, flow_name='')
    msgs = [
        _make_chat_message(1, 'question', '今天天气'),
        _make_chat_message(2, 'answer', '北京晴', parent_msg_id=1, sender='DeepSeek v3.2'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert len(turns) == 1
    assert turns[0].user_name == 'Admin'
    assert turns[0].user_query == '今天天气'
    assert turns[0].sender_name == 'DeepSeek v3.2'
    assert turns[0].answers == ['北京晴']


def test_build_turns_assistant():
    """AC-11: flow_type=5 (助手), 取 MessageSession.flow_name 当应用名。"""
    session = _make_session(flow_type=FlowType.ASSISTANT.value, flow_name='合同审核助手')
    msgs = [
        _make_chat_message(1, 'question', '帮我审一份合同'),
        _make_chat_message(2, 'answer', '好的', parent_msg_id=1, sender='ignored-model'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].sender_name == '合同审核助手'  # NOT 'ignored-model'


def test_build_turns_workflow_multi_answer():
    """AC-06: 单 query 多 answer (重新生成), 全部按 id 顺序保留。"""
    session = _make_session(flow_type=FlowType.WORKSTATION.value)
    msgs = [
        _make_chat_message(1, 'question', '介绍一下黄金'),
        _make_chat_message(2, 'answer', '答 v1', parent_msg_id=1, sender='M'),
        _make_chat_message(4, 'answer', '答 v2', parent_msg_id=1, sender='M'),
        _make_chat_message(7, 'answer', '答 v3', parent_msg_id=1, sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert len(turns) == 1
    assert turns[0].answers == ['答 v1', '答 v2', '答 v3']


def test_build_turns_workflow_nontext_output():
    """AC-09: workflow agent_answer 含非 text 输出 → [交互组件:xxx] 占位。"""
    session = _make_session(flow_type=FlowType.WORKFLOW.value, flow_name='合同审核流')
    payload = json.dumps(
        {
            'msg': '请填写下列表单',
            'events': [
                {'type': 'output', 'output_type': 'form', 'data': {'fields': []}},
                {'type': 'output', 'output_type': 'button', 'data': {'label': '确认'}},
            ],
        },
        ensure_ascii=False,
    )
    msgs = [
        _make_chat_message(1, 'question', '开启流程'),
        _make_chat_message(2, 'agent_answer', payload, parent_msg_id=1),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    text = turns[0].answers[0]
    assert '请填写下列表单' in text
    assert '[交互组件：form]' in text
    assert '[交互组件：button]' in text


def test_build_turns_agent_answer_msg_only():
    """AC-15: agent_answer 的 events thinking / tool_call 被丢弃, 只取 msg。"""
    session = _make_session(flow_type=FlowType.ASSISTANT.value, flow_name='Bot')
    payload = json.dumps(
        {
            'msg': '最终回答正文',
            'events': [
                {'type': 'thinking', 'content': '内部思考链…不应导出'},
                {'type': 'tool_call', 'tool_name': 'web_search'},
                {'type': 'tool_result', 'result': '结果…不应导出'},
            ],
        },
        ensure_ascii=False,
    )
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'agent_answer', payload, parent_msg_id=1),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    text = turns[0].answers[0]
    assert text == '最终回答正文'
    assert '内部思考' not in text
    assert 'web_search' not in text
    assert '结果' not in text


def test_build_turns_strip_citations():
    """AC-14: 私有 Unicode 角标 \\ue200…\\ue202 在 query 和 answer 中全部剥除。"""
    session = _make_session()
    # Citation pattern: <payload> with  separator
    answer_text = '答案前ref-1:item-1ref-2:item-2答案后'
    query_text = '问题前qref问题后'
    msgs = [
        _make_chat_message(1, 'question', query_text),
        _make_chat_message(2, 'answer', answer_text, parent_msg_id=1, sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].user_query == '问题前问题后'
    assert turns[0].answers == ['答案前答案后']
    # No marker chars should remain
    for ch in ('', '', ''):
        assert ch not in turns[0].user_query
        assert ch not in turns[0].answers[0]


def test_build_turns_strip_lone_citation_markers():
    """流式截断遗留的孤立 marker (start without end) 也要清理干净。"""
    session = _make_session()
    text = '答案A未闭合标记开始'  # missing 
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'answer', text, parent_msg_id=1, sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert '' not in turns[0].answers[0]


def test_build_turns_parent_message_id_missing_uses_time_adjacency():
    """spec §3: legacy 数据 extra 无 parentMessageId → 时间相邻 (id-based) 兜底配对。"""
    session = _make_session()
    msgs = [
        _make_chat_message(10, 'question', 'q1'),                              # 锚点 1
        _make_chat_message(11, 'answer', 'a1', sender='M'),                    # orphan -> 10
        _make_chat_message(20, 'question', 'q2'),                              # 锚点 2
        _make_chat_message(21, 'answer', 'a2', sender='M'),                    # orphan -> 20
        _make_chat_message(22, 'answer', 'a2-重试', sender='M'),                # orphan -> 20
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert len(turns) == 2
    assert turns[0].user_query == 'q1'
    assert turns[0].answers == ['a1']
    assert turns[1].user_query == 'q2'
    assert turns[1].answers == ['a2', 'a2-重试']


def test_build_turns_drops_tool_call_messages():
    """AC-15: 独立 ChatMessage 行 category=agent_tool_call/agent_thinking → 完全丢弃。"""
    session = _make_session()
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'agent_thinking', '思考中...', parent_msg_id=1),
        _make_chat_message(3, 'agent_tool_call', '{"tool":"x"}', parent_msg_id=1),
        _make_chat_message(4, 'answer', '最终答', parent_msg_id=1, sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert len(turns) == 1
    # Only the 'answer' survives; thinking/tool_call collapse to '' and are filtered out.
    assert turns[0].answers == ['最终答']


def test_build_turns_empty_input():
    """边界：没有 message → 返回空 turn 列表 (不抛)。"""
    session = _make_session()
    turns = ConversationExportService._build_turns([], session, user_name='Admin')
    assert turns == []


def test_build_turns_query_without_answer():
    """边界：query 没有对应 answer (用户刚提问就退出选择态) → query 单独成 turn。"""
    session = _make_session(flow_type=FlowType.WORKSTATION.value, flow_name='Workstation')
    msgs = [_make_chat_message(1, 'question', '今天天气')]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert len(turns) == 1
    assert turns[0].answers == []
    # Sender name falls back to flow_name when no answer
    assert turns[0].sender_name == 'Workstation'


# Issue: real workstation/workflow data wraps the user query in JSON envelopes
# rather than storing plain text. The renderer must unwrap before passing to
# Markdown, otherwise the export shows ``{"query": "..."}`` literally.

def test_build_turns_unwraps_daily_mode_query_envelope():
    """日常模式：``{"query": "...", "files": []}`` → 渲染为 query 字段内容。"""
    session = _make_session(flow_type=FlowType.WORKSTATION.value)
    msgs = [
        _make_chat_message(
            1, 'question',
            json.dumps({'query': '今天天气', 'files': []}, ensure_ascii=False),
        ),
        _make_chat_message(2, 'answer', '北京晴', sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].user_query == '今天天气'


def test_build_turns_unwraps_workflow_input_envelope():
    """工作流：``{"data": {...}, "input": "..."}`` → 渲染为 input 字段内容。"""
    session = _make_session(flow_type=FlowType.WORKFLOW.value, flow_name='搬家助手')
    msgs = [
        _make_chat_message(
            1, 'question',
            json.dumps(
                {'data': {'chatId': 'fc569', 'id': '265f9', 'type': 5},
                 'input': '引导问题1：如何根据物品数量和类型制定详细的搬家计划？'},
                ensure_ascii=False,
            ),
        ),
        _make_chat_message(2, 'answer', '答复', sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].user_query == '引导问题1：如何根据物品数量和类型制定详细的搬家计划？'


def test_build_turns_unwraps_query_then_strips_citations():
    """JSON 拆出来的 query 文本仍要走角标剥除（边界场景：user 问的内容也可能含角标，少见但理论上可能）。"""
    session = _make_session()
    payload = json.dumps(
        {'query': '问' + 'x' + '题', 'files': []},
        ensure_ascii=False,
    )
    msgs = [
        _make_chat_message(1, 'question', payload),
        _make_chat_message(2, 'answer', '答', sender='M'),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].user_query == '问题'


# Issue: agent_answer with empty ``msg`` but text content sitting in
# ``events`` (v2.5 agent-native format per chat_helpers.py:218-273). Previously
# such answers exported as empty turns.

def test_build_turns_agent_answer_falls_back_to_events_text():
    """``msg`` 为空时, 末尾 ``events`` 中的 text 块作为答复内容。"""
    session = _make_session(flow_type=FlowType.ASSISTANT.value, flow_name='Bot')
    payload = json.dumps({
        'msg': '',
        'events': [
            {'type': 'thinking', 'content': '思考...'},
            {'type': 'text', 'content': '最终答复正文'},
        ],
    }, ensure_ascii=False)
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'agent_answer', payload, parent_msg_id=1),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert turns[0].answers == ['最终答复正文']


def test_build_turns_agent_answer_workflow_text_output_captured():
    """工作流 OUTPUT 节点 ``output_type=text`` 也要被收进答复正文 (不只是占位)。"""
    session = _make_session(flow_type=FlowType.WORKFLOW.value, flow_name='流')
    payload = json.dumps({
        'msg': '',
        'events': [
            {'type': 'output', 'output_type': 'text', 'content': '工作流文本输出'},
            {'type': 'output', 'output_type': 'form'},  # 非 text → 占位
        ],
    }, ensure_ascii=False)
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'agent_answer', payload, parent_msg_id=1),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    text = turns[0].answers[0]
    assert '工作流文本输出' in text
    assert '[交互组件：form]' in text


def test_build_turns_agent_answer_strips_citations_from_events_text():
    """从 events 拿出来的 text 也要剥角标 (而不只剥 msg 字段)。"""
    session = _make_session(flow_type=FlowType.ASSISTANT.value, flow_name='Bot')
    payload = json.dumps({
        'msg': '',
        'events': [
            {'type': 'text', 'content': '答 ' + 'knowledgesearch_28624655:4' + ' 完'},
        ],
    }, ensure_ascii=False)
    msgs = [
        _make_chat_message(1, 'question', 'q'),
        _make_chat_message(2, 'agent_answer', payload, parent_msg_id=1),
    ]
    turns = ConversationExportService._build_turns(msgs, session, user_name='Admin')
    assert '' not in turns[0].answers[0]
    assert 'knowledgesearch' not in turns[0].answers[0]
    assert turns[0].answers[0] == '答  完'
