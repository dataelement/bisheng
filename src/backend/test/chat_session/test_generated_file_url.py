"""F016: signing the files the code interpreter attached to a daily-chat answer.

The owner signs through the existing attachment endpoint; an auditor signs
through the audit endpoint, which only ever reaches generated files -- user
uploads stay out of the audit scope (spec AC-17).

See features/v3.1.0-beta1/016-daily-chat-generated-files/design.md decision 5.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from bisheng.chat_session.api.endpoints import session as session_api
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.http_error import UnAuthorizedError

OWNER_ID = 7
STRANGER_ID = 99
AUDITOR_ID = 3


@pytest.fixture(autouse=True)
def not_found_response(monkeypatch):
    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.NotFoundError",
        SimpleNamespace(http_exception=lambda: HTTPException(status_code=404)),
    )


def _user(user_id):
    user = MagicMock()
    user.user_id = user_id
    user.tenant_id = 1
    return user


def _message(files):
    return SimpleNamespace(files=json.dumps(files))


UPLOAD = {"file_id": "u1", "filename": "in.xlsx", "object_name": "chat/7/in.xlsx"}
GENERATED = {
    "file_id": "g1",
    "file_name": "report.docx",
    "path": "output/report.docx",
    "source": "code_interpreter",
    "object_name": "chat/7/gen.docx",
    "filepath": "http://h/tmp-dir/gen.docx?sig",
}


@pytest.fixture
def storage():
    client = MagicMock()
    client.get_share_link = AsyncMock(return_value="/bisheng/chat/7/gen.docx?sig=fresh")
    client.remove_object = AsyncMock()
    with patch("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=client)):
        yield client


@pytest.fixture
def conversation():
    """A conversation owned by OWNER_ID: an upload on the question, a generated file on the answer."""
    session = SimpleNamespace(chat_id="c1", user_id=OWNER_ID, tenant_id=1, api_subject_type=None, is_delete=False)
    with (
        patch("bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one", AsyncMock(return_value=session)),
        patch(
            "bisheng.chat_session.domain.chat.WorkflowFileRepository.attachment_messages",
            AsyncMock(return_value=[_message([UPLOAD]), _message([GENERATED])]),
        ),
    ):
        yield session


def _audit_scope(allowed: bool):
    side_effect = None if allowed else UnAuthorizedError()
    return patch.object(
        session_api.AuditLogService, "assert_session_in_audit_scope", AsyncMock(side_effect=side_effect)
    )


async def test_owner_can_sign_bot_row_attachment(storage, conversation):
    url = await ChatSessionService.resolve_attachment_url("c1", "g1", _user(OWNER_ID))

    assert url == "/bisheng/chat/7/gen.docx?sig=fresh"
    assert storage.get_share_link.await_args.args[0] == "chat/7/gen.docx"


async def test_non_owner_rejected(storage, conversation):
    with pytest.raises(HTTPException):
        await ChatSessionService.resolve_attachment_url("c1", "g1", _user(STRANGER_ID))

    storage.get_share_link.assert_not_awaited()


async def test_audit_in_scope_signs(storage, conversation):
    with _audit_scope(True):
        resp = await session_api.get_chat_generated_file_url(chat_id="c1", file_id="g1", login_user=_user(AUDITOR_ID))

    assert resp.data == {"url": "/bisheng/chat/7/gen.docx?sig=fresh"}
    assert storage.get_share_link.await_args.args[0] == "chat/7/gen.docx"


async def test_audit_out_of_scope_rejected(storage, conversation):
    with _audit_scope(False), pytest.raises(HTTPException):
        await session_api.get_chat_generated_file_url(chat_id="c1", file_id="g1", login_user=_user(AUDITOR_ID))

    storage.get_share_link.assert_not_awaited()


async def test_audit_rejects_user_upload(storage, conversation):
    with _audit_scope(True), pytest.raises(HTTPException):
        await session_api.get_chat_generated_file_url(chat_id="c1", file_id="u1", login_user=_user(AUDITOR_ID))

    storage.get_share_link.assert_not_awaited()


async def test_missing_object_name_not_found(storage):
    session = SimpleNamespace(chat_id="c1", user_id=OWNER_ID, tenant_id=1, api_subject_type=None, is_delete=False)
    unpromoted = {**GENERATED, "object_name": None}
    with (
        patch("bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one", AsyncMock(return_value=session)),
        patch(
            "bisheng.chat_session.domain.chat.WorkflowFileRepository.attachment_messages",
            AsyncMock(return_value=[_message([unpromoted])]),
        ),
        pytest.raises(HTTPException),
    ):
        await ChatSessionService.resolve_audit_attachment_url("c1", "g1")

    storage.get_share_link.assert_not_awaited()


async def test_delete_session_removes_bot_row_objects(storage, conversation):
    await ChatSessionService._remove_attachments("c1")

    removed = {c.kwargs["object_name"] for c in storage.remove_object.await_args_list}
    assert removed == {"chat/7/in.xlsx", "chat/7/gen.docx"}
