"""F028 T014 — integration tests for the /chat/messages export+import endpoints.

These mount the real router on a minimal FastAPI app + TestClient. Service
behavior is patched at the service-method boundary, so we verify only the API
contract: routing, dependency injection, error envelope, Content-Type +
Content-Disposition headers, and request body validation.

Service-level logic is covered separately by T007/T009/T011/T013 unit tests.

AC coverage: AC-02, AC-08, AC-18, AC-21, AC-25, AC-30, AC-31
"""

from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette import status

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode


# Mirror bisheng.main._EXCEPTION_HANDLERS without importing main (main has a
# heavy import chain — assistant.py, langchain, etc. — that explodes in test
# environments without the production initialization sequence).
def _handle_http_exception(req, exc):
    if isinstance(exc, HTTPException):
        msg = {'status_code': exc.status_code, 'status_message': exc.detail}
    elif isinstance(exc, BaseErrorCode):
        data = {'exception': str(exc), **exc.kwargs} if exc.kwargs else {'exception': str(exc)}
        msg = {'status_code': exc.code, 'status_message': exc.message, 'data': data}
    else:
        msg = {'status_code': 500, 'status_message': str(exc)}
    return ORJSONResponse(content=msg)


def _handle_validation_error(req, exc):
    return ORJSONResponse(
        content={'status_code': status.HTTP_422_UNPROCESSABLE_ENTITY, 'status_message': exc.errors()},
    )


_EXCEPTION_HANDLERS = {
    HTTPException: _handle_http_exception,
    RequestValidationError: _handle_validation_error,
    BaseErrorCode: _handle_http_exception,
}
from bisheng.common.errcode.workstation import (
    ConversationExportRenderFailedError,
    ConversationImportSpaceNotFoundError,
    ConversationMessageBatchTooLargeError,
    ConversationMessageNotFoundError,
)
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.workstation.api.endpoints.conversation_export import (
    router as export_router,
)
from bisheng.workstation.domain.schemas.conversation_export import (
    ImportMessagesToKnowledgeResponse,
)
from bisheng.workstation.domain.services import conversation_export_service as svc_mod


# --- App + client fixtures -------------------------------------------------


class _FakeUser:
    def __init__(self, user_id=1, user_name='Admin', tenant_id=1):
        self.user_id = user_id
        self.user_name = user_name
        self.tenant_id = tenant_id

    def is_admin(self):
        return False


def _make_app(user_factory=_FakeUser, space_service=None) -> FastAPI:
    # exception_handlers mirror production main.create_app() so BaseErrorCode
    # raises are converted to the standard JSON envelope (200 body with code).
    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    app.include_router(export_router, prefix='/api/v1')

    async def _get_user():
        return user_factory()

    app.dependency_overrides[UserPayload.get_login_user] = _get_user

    if space_service is not None:
        async def _get_space_service():
            return space_service
        app.dependency_overrides[get_knowledge_space_service] = _get_space_service

    return app


def _stub_session(name='今日黄金行情'):
    return MessageSession(
        chat_id='chat-1', flow_id='flow-1', flow_type=15, user_id=1,
        flow_name='Workstation', name=name, tenant_id=1,
    )


# --- export endpoint -------------------------------------------------------


def test_export_pdf_returns_file_stream(monkeypatch):
    """AC-02 / AC-10 / AC-11: POST /export with format=pdf → 200 + application/pdf
    body + Content-Disposition with RFC5987-encoded Chinese filename."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        return [], _stub_session()

    def _fake_build_turns(messages, session, *, user_name):
        return []

    def _fake_render_markdown(turns):
        return '**Admin：**\n\n你好\n'

    def _fake_render_pdf(md):
        return b'%PDF-1.4\nfake pdf bytes\n%%EOF'

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_build_turns', classmethod(lambda cls, *a, **kw: _fake_build_turns(*a, **kw)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_markdown', classmethod(lambda cls, t: _fake_render_markdown(t)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_pdf', classmethod(lambda cls, m: _fake_render_pdf(m)))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1, 2], 'format': 'pdf'},
        )
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'application/pdf'
    cd = resp.headers['content-disposition']
    # RFC5987 form must be present
    assert "filename*=UTF-8''" in cd
    # Encoded Chinese filename — full name contains the percent-encoded title
    assert quote('今日黄金行情', safe='') in cd
    # Body is the file bytes
    assert resp.content.startswith(b'%PDF')


def test_export_markdown_returns_utf8_text(monkeypatch):
    """AC-02 / AC-12: format=md → text/markdown; charset=utf-8."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        return [], _stub_session()

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_build_turns', classmethod(lambda cls, *a, **kw: []))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_markdown', classmethod(lambda cls, t: '**Admin：**\n\nq\n'))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1], 'format': 'md'},
        )
    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/markdown')
    assert resp.content == b'**Admin\xef\xbc\x9a**\n\nq\n'


def test_export_docx_returns_zip_bytes(monkeypatch):
    """AC-02: format=docx → vnd.openxmlformats... + raw bytes preserved."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        return [], _stub_session()

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_build_turns', classmethod(lambda cls, *a, **kw: []))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_markdown', classmethod(lambda cls, t: 'x'))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_docx', classmethod(lambda cls, m: b'PK\x03\x04fake-docx-zip-bytes'))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1], 'format': 'docx'},
        )
    assert resp.status_code == 200
    assert 'wordprocessingml' in resp.headers['content-type']
    assert resp.content.startswith(b'PK\x03\x04')


def test_export_format_unsupported_returns_422_from_pydantic():
    """AC-31: format='xlsx' is not in the enum → Pydantic validation rejects.

    bisheng signals validation errors as HTTP 200 with ``body.status_code=422``
    (matches production handle_request_validation_error)."""
    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1], 'format': 'xlsx'},
        )
    body = resp.json()
    assert body['status_code'] == 422
    assert 'format' in str(body['status_message'])


def test_export_batch_too_large_returns_422_from_pydantic():
    """AC-08: > 200 message_ids — Pydantic Field(max_length=200) blocks before
    the service even runs."""
    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={
                'chat_id': 'chat-1',
                'message_ids': list(range(1, 202)),
                'format': 'pdf',
            },
        )
    body = resp.json()
    assert body['status_code'] == 422


def test_export_service_propagates_batch_too_large_when_bypassed(monkeypatch):
    """If DTO validation is somehow bypassed (e.g. direct service call),
    the service-side 12061 still surfaces correctly through the endpoint."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        raise ConversationMessageBatchTooLargeError()

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1, 2], 'format': 'pdf'},
        )
    # The middleware turns BaseErrorCode raises into HTTP 500 OR 200-with-body
    # depending on the project conventions; either way, the code field is 12061.
    body = resp.json()
    assert resp.status_code in (200, 500)
    # Walk body to find the error code (envelope shape may differ)
    body_str = str(body)
    assert '12061' in body_str


def test_export_message_not_found_surfaces_as_12060(monkeypatch):
    """AC-27: missing message ids → 12060 surfaces through endpoint."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        raise ConversationMessageNotFoundError(msg='消息不存在')

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [9999], 'format': 'pdf'},
        )
    assert '12060' in str(resp.json())


def test_export_render_failed_surfaces_as_12064(monkeypatch):
    """AC-30: pandoc / LibreOffice render failure → 12064."""

    async def _fake_load(*, chat_id, message_ids, user_id):
        return [], _stub_session()

    def _boom_pdf(md):
        raise ConversationExportRenderFailedError(msg='soffice 超时')

    monkeypatch.setattr(svc_mod.ConversationExportService, '_load_and_validate_messages', classmethod(lambda cls, **kw: _fake_load(**kw)))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_build_turns', classmethod(lambda cls, *a, **kw: []))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_markdown', classmethod(lambda cls, t: 'x'))
    monkeypatch.setattr(svc_mod.ConversationExportService, '_render_pdf', classmethod(lambda cls, m: _boom_pdf(m)))

    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/export',
            json={'chat_id': 'chat-1', 'message_ids': [1], 'format': 'pdf'},
        )
    assert '12064' in str(resp.json())


# --- import endpoint -------------------------------------------------------


class _FakeSpaceService:
    """Stand-in for ``KnowledgeSpaceService`` (injected via dependency override).

    Only the methods touched by the endpoint pipeline need real behavior; the
    actual import flow is mocked at ``import_messages_to_knowledge`` so the
    test verifies wiring rather than inner mechanics.
    """


def test_import_happy_path(monkeypatch):
    """AC-18: POST /import-to-knowledge returns {file_id, target_filename, dup_renamed}."""

    async def _fake_import(req, user, space_service):
        return ImportMessagesToKnowledgeResponse(
            file_id=99887, target_filename='关于黄金的对话_202602031117.md', dup_renamed=False,
        )

    monkeypatch.setattr(
        svc_mod.ConversationExportService,
        'import_messages_to_knowledge',
        classmethod(lambda cls, req, user, space_service: _fake_import(req, user, space_service)),
    )

    app = _make_app(space_service=_FakeSpaceService())
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/import-to-knowledge',
            json={
                'chat_id': 'chat-1',
                'message_ids': [1, 2],
                'knowledge_space_id': 42,
                'parent_id': None,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body['status_code'] == 200
    assert body['data']['file_id'] == 99887
    assert body['data']['target_filename'] == '关于黄金的对话_202602031117.md'
    assert body['data']['dup_renamed'] is False


def test_import_dup_renamed_reflected_in_response(monkeypatch):
    """AC-19: dup_renamed=True 透传到 HTTP 响应。"""

    async def _fake_import(req, user, space_service):
        return ImportMessagesToKnowledgeResponse(
            file_id=99888, target_filename='xxx(1).md', dup_renamed=True,
        )

    monkeypatch.setattr(
        svc_mod.ConversationExportService,
        'import_messages_to_knowledge',
        classmethod(lambda cls, req, user, space_service: _fake_import(req, user, space_service)),
    )

    app = _make_app(space_service=_FakeSpaceService())
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/import-to-knowledge',
            json={
                'chat_id': 'chat-1',
                'message_ids': [1],
                'knowledge_space_id': 42,
                'parent_id': 1024,
            },
        )
    body = resp.json()
    assert body['data']['dup_renamed'] is True
    assert body['data']['target_filename'].endswith('(1).md')


def test_import_missing_space_surfaces_as_12065(monkeypatch):
    """AC-21: 空间不存在 → 12065 (从 service 透传)。"""

    async def _fake_import(req, user, space_service):
        raise ConversationImportSpaceNotFoundError()

    monkeypatch.setattr(
        svc_mod.ConversationExportService,
        'import_messages_to_knowledge',
        classmethod(lambda cls, req, user, space_service: _fake_import(req, user, space_service)),
    )

    app = _make_app(space_service=_FakeSpaceService())
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/import-to-knowledge',
            json={
                'chat_id': 'chat-1',
                'message_ids': [1],
                'knowledge_space_id': 9999,
                'parent_id': None,
            },
        )
    assert '12065' in str(resp.json())


def test_import_validates_empty_message_ids():
    """message_ids 长度 0 → Pydantic 验证拒绝 (body.status_code=422)。"""
    app = _make_app(space_service=_FakeSpaceService())
    with TestClient(app) as client:
        resp = client.post(
            '/api/v1/chat/messages/import-to-knowledge',
            json={
                'chat_id': 'chat-1',
                'message_ids': [],
                'knowledge_space_id': 42,
                'parent_id': None,
            },
        )
    body = resp.json()
    assert body['status_code'] == 422
