"""F028 T011 — unit tests for the conversation import-to-knowledge flow.

Scope: ``ConversationExportService.import_messages_to_knowledge`` end-to-end,
with MinIO, KnowledgeDao, KnowledgeFileDao, SpaceFileDao and the injected
KnowledgeSpaceService all mocked. We verify error mapping for every spec
error code (12060-12069) and the dedup → race-retry path.

AC coverage: AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceFileNameDuplicateError,
    SpaceFileSizeLimitError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError
from bisheng.common.errcode.workstation import (
    ConversationImportFailedError,
    ConversationImportFolderNotFoundError,
    ConversationImportPermissionDeniedError,
    ConversationImportQuotaExceededError,
    ConversationImportSpaceNotFoundError,
)
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.user.domain.services.auth import LoginUser
from bisheng.workstation.domain.schemas.conversation_export import (
    ImportMessagesToKnowledgeRequest,
)
from bisheng.workstation.domain.services import conversation_export_service as svc_mod
from bisheng.workstation.domain.services.conversation_export_service import (
    ConversationExportService,
)


# --- Fixtures --------------------------------------------------------------


def _make_chat_message(id_: int, category: str, content: str, *, parent_msg_id: Optional[int] = None) -> ChatMessage:
    import json
    extra = json.dumps({'parentMessageId': parent_msg_id}) if parent_msg_id is not None else None
    return ChatMessage(
        id=id_,
        is_bot=(category != 'question'),
        chat_id='chat-1', user_id=1, flow_id='flow-1',
        type='human' if category == 'question' else 'assistant',
        category=category, message=content, sender='M',
        extra=extra, tenant_id=1,
    )


def _make_session(name: str = '今日黄金行情', flow_type: int = 15) -> MessageSession:
    return MessageSession(
        chat_id='chat-1', flow_id='flow-1', flow_type=flow_type, user_id=1,
        flow_name='Workstation', name=name, tenant_id=1,
    )


def _login_user() -> LoginUser:
    return LoginUser(user_id=1, user_name='Admin', user_role=[], tenant_id=1)


@dataclass
class _FakeSpaceFile:
    id: int
    file_name: str
    file_type: int = 0


@dataclass
class _FakeKnowledgeFile:
    id: int
    file_name: str
    file_type: int


@dataclass
class _FakeKnowledge:
    id: int
    type: int = KnowledgeTypeEnum.SPACE.value
    tenant_id: int = 1


@dataclass
class _FakeAddFileResponse:
    id: int
    file_name: str


class _FakeSpaceService:
    """Lightweight stand-in for KnowledgeSpaceService.

    Tests configure ``require_permission_raises`` / ``add_file_raises`` /
    ``add_file_returns`` to drive each branch. ``add_file_attempts`` records
    each invocation so dedup-retry tests can assert call count + filenames.
    """

    def __init__(self):
        self.require_permission_raises: Optional[Exception] = None
        self.add_file_raises_sequence: list[Optional[Exception]] = []
        self.add_file_returns_sequence: list[list] = []
        self.add_file_attempts: list[dict] = []

    async def _require_permission_id(self, object_type, object_id, permission_id, *, space_id=None):
        if self.require_permission_raises is not None:
            raise self.require_permission_raises

    async def add_file(self, knowledge_id, file_path, parent_id=None, file_source=None, **kw):
        attempt_idx = len(self.add_file_attempts)
        self.add_file_attempts.append({
            'knowledge_id': knowledge_id,
            'file_path': list(file_path),
            'parent_id': parent_id,
        })
        # If a sequence of failures is queued, raise the next.
        if attempt_idx < len(self.add_file_raises_sequence):
            exc = self.add_file_raises_sequence[attempt_idx]
            if exc is not None:
                raise exc
        if attempt_idx < len(self.add_file_returns_sequence):
            return self.add_file_returns_sequence[attempt_idx]
        # Default: a single successful file response.
        return [_FakeAddFileResponse(id=999 + attempt_idx, file_name=file_path[0].rsplit('/', 1)[-1])]


@pytest.fixture
def patch_import_deps(monkeypatch: pytest.MonkeyPatch):
    """Registry that pre-loads DAO + helper mocks for each test scenario."""

    state = {
        'session': _make_session(),
        'messages': [
            _make_chat_message(1, 'question', '你好'),
            _make_chat_message(2, 'answer', '你好！', parent_msg_id=1),
        ],
        'space': _FakeKnowledge(id=42),
        'folder': None,           # set when test traverses parent_id branch
        'children': [],           # SpaceFileDao.async_list_children result
        'save_calls': [],         # captured (filename, bytes) tuples
    }

    async def _fake_session_get(_cls, _chat_id):
        return state['session']

    async def _fake_messages_get(_cls, message_ids, user_id, chat_id):
        return [
            m for m in state['messages']
            if m.id in message_ids and m.user_id == user_id and m.chat_id == chat_id
        ]

    async def _fake_knowledge_get(_cls, _kid):
        return state['space']

    async def _fake_folder_get(_cls, _fid):
        return state['folder']

    async def _fake_list_children(_cls, knowledge_id, parent_id, page=1, page_size=1000):
        return list(state['children'])

    async def _fake_save_uploaded_file(file, folder_name, file_name, bucket_name=None):
        body = await file.read()
        state['save_calls'].append({'filename': file_name, 'bytes': body, 'folder': folder_name})
        return f'minio://{folder_name}/{file_name}'

    monkeypatch.setattr(MessageSessionDao, 'async_get_one', classmethod(_fake_session_get))
    monkeypatch.setattr(ChatMessageDao, 'aget_messages_by_ids', classmethod(_fake_messages_get))
    monkeypatch.setattr(KnowledgeDao, 'aquery_by_id', classmethod(_fake_knowledge_get))
    monkeypatch.setattr(KnowledgeFileDao, 'query_by_id', classmethod(_fake_folder_get))
    monkeypatch.setattr(SpaceFileDao, 'async_list_children', classmethod(_fake_list_children))
    monkeypatch.setattr(svc_mod, 'save_uploaded_file', _fake_save_uploaded_file)

    class _Registry:
        @staticmethod
        def set_session(s): state['session'] = s
        @staticmethod
        def set_messages(rows): state['messages'] = list(rows)
        @staticmethod
        def set_space(sp): state['space'] = sp
        @staticmethod
        def set_folder(f): state['folder'] = f
        @staticmethod
        def set_children(rows): state['children'] = list(rows)
        @staticmethod
        def saved_calls(): return state['save_calls']

    return _Registry()


def _build_request(parent_id: Optional[int] = None) -> ImportMessagesToKnowledgeRequest:
    return ImportMessagesToKnowledgeRequest(
        chat_id='chat-1',
        message_ids=[1, 2],
        knowledge_space_id=42,
        parent_id=parent_id,
    )


# --- happy path -------------------------------------------------------------


async def test_import_happy_path(patch_import_deps):
    """AC-18: 选 2 条 message, 根目录, 生成 .md, add_file 入队成功 → file_id + dup_renamed=False。"""
    space_service = _FakeSpaceService()
    resp = await ConversationExportService.import_messages_to_knowledge(
        _build_request(), _login_user(), space_service,
    )
    assert resp.dup_renamed is False
    assert resp.file_id == 999
    assert resp.target_filename.endswith('.md')
    assert '今日黄金行情' in resp.target_filename

    # Exactly one add_file invocation, file_path went through MinIO save helper
    assert len(space_service.add_file_attempts) == 1
    saved = patch_import_deps.saved_calls()
    assert len(saved) == 1
    # Body is Markdown encoded UTF-8 with the user + sender labels
    body = saved[0]['bytes'].decode('utf-8')
    assert '**Admin：**' in body
    assert '**M：**' in body


# --- dedup ------------------------------------------------------------------


async def test_import_dup_renamed_to_1(patch_import_deps):
    """AC-19: 目标层级已存在同名文件 → 落地 xxx(1).md, dup_renamed=True。"""
    base = ConversationExportService._resolve_filename(_make_session(), 'md')
    patch_import_deps.set_children([_FakeSpaceFile(id=1, file_name=base)])

    space_service = _FakeSpaceService()
    resp = await ConversationExportService.import_messages_to_knowledge(
        _build_request(), _login_user(), space_service,
    )
    assert resp.dup_renamed is True
    assert resp.target_filename.endswith('(1).md')
    # Saved MinIO key reflects the dedup-resolved name
    assert patch_import_deps.saved_calls()[0]['filename'] == resp.target_filename


async def test_import_dup_renamed_to_5(patch_import_deps):
    """AC-19: 同名 base/(1)/(2)/(3)/(4) 都已存在 → 落地 (5)。"""
    base = ConversationExportService._resolve_filename(_make_session(), 'md')
    stem = base[:-3]  # strip '.md'
    existing = [base] + [f'{stem}({i}).md' for i in range(1, 5)]
    patch_import_deps.set_children([_FakeSpaceFile(id=i, file_name=n) for i, n in enumerate(existing, start=1)])

    space_service = _FakeSpaceService()
    resp = await ConversationExportService.import_messages_to_knowledge(
        _build_request(), _login_user(), space_service,
    )
    assert resp.dup_renamed is True
    assert resp.target_filename == f'{stem}(5).md'


async def test_import_dup_race_retry_once(patch_import_deps, monkeypatch):
    """spec §3 dup race: add_file 第一次报重名 → 我们重新扫描重命名 → 重试 1 次 → 成功。

    Simulates a race window: the first list_children() returns empty so the
    pre-add_file dedup produces the base filename; the racing neighbor lands
    between our scan and add_file; on the second pass list_children() yields
    the collision so we land on ``(1).md``.
    """
    base = ConversationExportService._resolve_filename(_make_session(), 'md')
    raced_children = [_FakeSpaceFile(id=99, file_name=base)]
    call_count = {'n': 0}

    async def _list_children_with_race(_cls, knowledge_id, parent_id, page=1, page_size=1000):
        call_count['n'] += 1
        return [] if call_count['n'] == 1 else raced_children

    monkeypatch.setattr(
        SpaceFileDao, 'async_list_children',
        classmethod(_list_children_with_race),
    )

    space_service = _FakeSpaceService()
    space_service.add_file_raises_sequence = [SpaceFileNameDuplicateError(), None]

    resp = await ConversationExportService.import_messages_to_knowledge(
        _build_request(), _login_user(), space_service,
    )
    assert len(space_service.add_file_attempts) == 2  # retried once
    assert resp.target_filename.endswith('(1).md')


async def test_import_dup_race_fail_after_retry(patch_import_deps):
    """spec §3: 重试仍 SpaceFileNameDuplicateError → ConversationImportFailedError (12069)。"""
    space_service = _FakeSpaceService()
    space_service.add_file_raises_sequence = [
        SpaceFileNameDuplicateError(),
        SpaceFileNameDuplicateError(),
    ]
    with pytest.raises(ConversationImportFailedError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )
    assert len(space_service.add_file_attempts) == 2


# --- pre-checks ------------------------------------------------------------


async def test_import_space_not_found(patch_import_deps):
    """AC-21: 空间查不到 → ConversationImportSpaceNotFoundError (12065), 不调 add_file。"""
    patch_import_deps.set_space(None)
    space_service = _FakeSpaceService()
    with pytest.raises(ConversationImportSpaceNotFoundError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )
    assert space_service.add_file_attempts == []


async def test_import_space_wrong_type(patch_import_deps):
    """AC-21: 资源 type 不是 KnowledgeTypeEnum.SPACE → 仍当作 SpaceNotFound (12065)。"""
    patch_import_deps.set_space(_FakeKnowledge(id=42, type=KnowledgeTypeEnum.NORMAL.value))
    space_service = _FakeSpaceService()
    with pytest.raises(ConversationImportSpaceNotFoundError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )


async def test_import_folder_not_found(patch_import_deps):
    """AC-22: parent_id 指向不存在的文件夹 → ConversationImportFolderNotFoundError (12066)。"""
    patch_import_deps.set_folder(None)
    space_service = _FakeSpaceService()
    with pytest.raises(ConversationImportFolderNotFoundError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(parent_id=1024), _login_user(), space_service,
        )
    assert space_service.add_file_attempts == []


async def test_import_folder_wrong_type(patch_import_deps):
    """AC-22: parent_id 指向的不是 DIR → 仍当作 FolderNotFound。"""
    patch_import_deps.set_folder(_FakeKnowledgeFile(id=1024, file_name='不是文件夹.md', file_type=FileType.FILE.value))
    space_service = _FakeSpaceService()
    with pytest.raises(ConversationImportFolderNotFoundError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(parent_id=1024), _login_user(), space_service,
        )


async def test_import_permission_denied_pre_check(patch_import_deps):
    """AC-20: preflight _require_permission_id 抛 → 12067, 不调 add_file 也不调 MinIO save。"""
    space_service = _FakeSpaceService()
    space_service.require_permission_raises = SpacePermissionDeniedError()
    with pytest.raises(ConversationImportPermissionDeniedError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )
    assert space_service.add_file_attempts == []
    assert patch_import_deps.saved_calls() == []  # MinIO not touched


# --- quota & misc errors ----------------------------------------------------


async def test_import_quota_exceeded(patch_import_deps):
    """AC-23: add_file 抛 TenantStorageQuotaExceededError → 映射为 12068。"""
    space_service = _FakeSpaceService()
    space_service.add_file_raises_sequence = [
        TenantStorageQuotaExceededError(msg='Storage quota exceeded', used_gb=10, quota_gb=10, tenant_name='t', tenant_id=1, reason='cap'),
    ]
    with pytest.raises(ConversationImportQuotaExceededError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )


async def test_import_file_size_limit_mapped_to_quota(patch_import_deps):
    """SpaceFileSizeLimitError (单文件超限) → 也归到 12068 配额族。"""
    space_service = _FakeSpaceService()
    space_service.add_file_raises_sequence = [SpaceFileSizeLimitError()]
    with pytest.raises(ConversationImportQuotaExceededError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )


async def test_import_add_file_unknown_error(patch_import_deps):
    """add_file 抛任何未识别的异常 → ConversationImportFailedError (12069) 兜底。"""
    space_service = _FakeSpaceService()
    space_service.add_file_raises_sequence = [RuntimeError('downstream blew up')]
    with pytest.raises(ConversationImportFailedError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )


async def test_import_add_file_empty_response(patch_import_deps):
    """add_file 不抛但返回空 list → 12069 (不应静默失败)。"""
    space_service = _FakeSpaceService()
    space_service.add_file_returns_sequence = [[]]
    with pytest.raises(ConversationImportFailedError):
        await ConversationExportService.import_messages_to_knowledge(
            _build_request(), _login_user(), space_service,
        )


# --- folder branch ----------------------------------------------------------


async def test_import_to_folder_calls_correct_permission_check(patch_import_deps):
    """AC-20/22: parent_id 提供时, preflight 调用 folder 维度的 _require_permission_id。"""
    patch_import_deps.set_folder(_FakeKnowledgeFile(id=2048, file_name='宏观研究', file_type=FileType.DIR.value))

    captured = {}

    class _CapturingSpaceService(_FakeSpaceService):
        async def _require_permission_id(self, object_type, object_id, permission_id, *, space_id=None):
            captured['object_type'] = object_type
            captured['object_id'] = object_id
            captured['permission_id'] = permission_id
            captured['space_id'] = space_id

    space_service = _CapturingSpaceService()
    await ConversationExportService.import_messages_to_knowledge(
        _build_request(parent_id=2048), _login_user(), space_service,
    )
    assert captured == {
        'object_type': 'folder', 'object_id': 2048,
        'permission_id': 'upload_file', 'space_id': 42,
    }
    assert space_service.add_file_attempts[0]['parent_id'] == 2048
