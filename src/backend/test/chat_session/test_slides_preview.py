"""PDF preview of a slide deck kept on a conversation.

A deck a direct answer generated has no deep-research version, so the F111
task-result preview cannot resolve it. ``ChatSessionService.slides_preview``
finds the deck on the conversation's own rows and lets the owner or a holder
of a share link to that conversation read it.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from bisheng.chat_session.domain.chat import ChatSessionService, slides_preview_key

OWNER_ID = 7
STRANGER_ID = 99
DECK = "chat/1/7/answers/run-1/deck.pptx"
READY = {"status": "ready", "file_path": "/bisheng/deck.pdf?sig=1"}


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


def _share(resource_id):
    return SimpleNamespace(resource_id=resource_id, meta_data=None)


@pytest.fixture
def conversation():
    session = SimpleNamespace(chat_id="c1", user_id=OWNER_ID, tenant_id=1, api_subject_type=None, is_delete=False)
    files = [
        {"file_id": "f1", "file_name": "deck.pptx", "object_name": DECK, "workspace_file_id": "ev-1"},
        {"file_id": "f2", "file_name": "notes.md", "object_name": "chat/1/7/answers/run-1/notes.md"},
    ]
    with (
        patch(
            "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
            AsyncMock(return_value=session),
        ),
        patch(
            "bisheng.chat_session.domain.chat.WorkflowFileRepository.attachment_messages",
            AsyncMock(return_value=[SimpleNamespace(files=json.dumps(files))]),
        ),
    ):
        yield session


@pytest.fixture
def preview():
    with patch(
        "bisheng.linsight.domain.services.artifact_preview_service.preview_slides_as_pdf",
        AsyncMock(return_value=READY),
    ) as mocked:
        yield mocked


async def test_owner_previews_the_recorded_deck(conversation, preview):
    result = await ChatSessionService.slides_preview("c1", "f1", _user(OWNER_ID))

    assert result == READY
    assert preview.await_args.args[0] == DECK
    assert preview.await_args.kwargs["preview_key"] == slides_preview_key(DECK)


async def test_share_link_to_the_conversation_grants_preview(conversation, preview):
    result = await ChatSessionService.slides_preview("c1", "f1", _user(STRANGER_ID), _share("c1"))

    assert result == READY


async def test_stranger_is_refused(conversation, preview):
    with pytest.raises(HTTPException):
        await ChatSessionService.slides_preview("c1", "f1", _user(STRANGER_ID))
    preview.assert_not_awaited()


async def test_share_link_to_another_conversation_is_refused(conversation, preview):
    with pytest.raises(HTTPException):
        await ChatSessionService.slides_preview("c1", "f1", _user(STRANGER_ID), _share("other"))
    preview.assert_not_awaited()


async def test_live_event_id_resolves_to_the_kept_copy(conversation, preview):
    await ChatSessionService.slides_preview("c1", "ev-1", _user(OWNER_ID), alias_key="workspace_file_id")

    assert preview.await_args.args[0] == DECK


async def test_non_slide_attachment_is_not_converted(conversation, preview):
    with pytest.raises(HTTPException):
        await ChatSessionService.slides_preview("c1", "f2", _user(OWNER_ID))
    preview.assert_not_awaited()


async def test_unknown_file_is_not_found(conversation, preview):
    with pytest.raises(HTTPException):
        await ChatSessionService.slides_preview("c1", "nope", _user(OWNER_ID))
    preview.assert_not_awaited()


async def test_deleting_the_conversation_also_removes_the_preview_pdf(conversation):
    client = MagicMock()
    client.remove_object = AsyncMock()
    with patch("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=client)):
        await ChatSessionService._remove_attachments("c1")

    removed = {call.kwargs["object_name"] for call in client.remove_object.await_args_list}
    assert slides_preview_key(DECK) in removed
    assert DECK in removed
    assert "chat/1/7/answers/run-1/notes.md.preview.pdf" not in removed
