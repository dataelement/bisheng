"""F043: handing out a fresh link for a conversation attachment.

Links issued at upload time expire, so the client asks for a new one when it
renders. The object name must only ever come from what the server has stored
for that conversation -- an endpoint that signed whatever object name the
caller passed would hand out the entire bucket.

See features/v2.6.0/043-chat-file-permanent-storage/design.md §3 decision 3.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from bisheng.chat_session.domain.chat import ChatSessionService

OWNER_ID = 7
STRANGER_ID = 99


def _user(user_id):
    user = MagicMock()
    user.user_id = user_id
    user.tenant_id = 1
    return user


def _message(files):
    return SimpleNamespace(files=json.dumps(files))


@pytest.fixture
def storage():
    client = MagicMock()
    client.get_share_link = AsyncMock(return_value="/bisheng/chat/7/abc.png?sig=fresh")
    with patch("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=client)):
        yield client


@pytest.fixture
def conversation():
    """A conversation owned by OWNER_ID holding one attachment."""
    session = SimpleNamespace(
        chat_id="c1",
        user_id=OWNER_ID,
        tenant_id=1,
        api_subject_type=None,
        is_delete=False,
    )
    files = [{"file_id": "f1", "filename": "a.png", "object_name": "chat/7/abc.png"}]
    with (
        patch(
            "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
            AsyncMock(return_value=session),
        ),
        patch(
            "bisheng.chat_session.domain.chat.ChatMessageDao.aget_messages_by_chat_id",
            AsyncMock(return_value=[_message(files)]),
        ),
    ):
        yield session


class TestResolveAttachmentUrl:
    async def test_owner_gets_a_fresh_link(self, storage, conversation):
        url = await ChatSessionService.resolve_attachment_url("c1", "f1", _user(OWNER_ID))

        assert url == "/bisheng/chat/7/abc.png?sig=fresh"
        # Signed for the object the server recorded, nothing else.
        assert storage.get_share_link.await_args.args[0] == "chat/7/abc.png"

    async def test_someone_else_is_refused(self, storage, conversation):
        # AC-04 — conversation ownership is the whole authorization story.
        with pytest.raises(Exception):
            await ChatSessionService.resolve_attachment_url("c1", "f1", _user(STRANGER_ID))

        storage.get_share_link.assert_not_awaited()

    async def test_unknown_file_id_is_refused(self, storage, conversation):
        with pytest.raises(Exception):
            await ChatSessionService.resolve_attachment_url("c1", "nope", _user(OWNER_ID))

        storage.get_share_link.assert_not_awaited()

    async def test_attachment_without_object_name_is_refused(self, storage):
        # Messages written before this feature carry no object name; they must
        # read as "gone", not fall back to guessing at some other object.
        session = SimpleNamespace(
            chat_id="c1",
            user_id=OWNER_ID,
            tenant_id=1,
            api_subject_type=None,
            is_delete=False,
        )
        legacy = [{"file_id": "f1", "filename": "a.png", "filepath": "/bisheng-tmp/a.png"}]
        with (
            patch(
                "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
                AsyncMock(return_value=session),
            ),
            patch(
                "bisheng.chat_session.domain.chat.ChatMessageDao.aget_messages_by_chat_id",
                AsyncMock(return_value=[_message(legacy)]),
            ),
            pytest.raises(Exception),
        ):
            await ChatSessionService.resolve_attachment_url("c1", "f1", _user(OWNER_ID))

        storage.get_share_link.assert_not_awaited()

    async def test_missing_conversation_is_refused(self, storage):
        with (
            patch(
                "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
                AsyncMock(return_value=None),
            ),
            pytest.raises(Exception),
        ):
            await ChatSessionService.resolve_attachment_url("nope", "f1", _user(OWNER_ID))

        storage.get_share_link.assert_not_awaited()


class TestResolveSubjectAttachmentUrl:
    """F078: the workflow Open API downloads agent deliverables by its own identity."""

    @staticmethod
    def _subject(service_account_id=5, external_user_id="u-1", tenant_id=1):
        from bisheng.chat_session.domain.session_subject import SessionSubject

        return SessionSubject.service_account(
            tenant_id=tenant_id,
            service_account_id=service_account_id,
            resource_owner_user_id=OWNER_ID,
            external_user_id=external_user_id,
        )

    @pytest.fixture
    def api_conversation(self, conversation):
        conversation.api_subject_type = "service_account"
        conversation.api_subject_id = 5
        conversation.external_user_id = "u-1"
        return conversation

    async def test_owning_caller_gets_a_fresh_link(self, storage, api_conversation):
        url = await ChatSessionService.resolve_subject_attachment_url("c1", "f1", self._subject())

        assert url == "/bisheng/chat/7/abc.png?sig=fresh"
        assert storage.get_share_link.await_args.args[0] == "chat/7/abc.png"

    @pytest.mark.parametrize(
        "subject_kwargs",
        [
            {"service_account_id": 6},  # another service account
            {"external_user_id": "u-2"},  # same account, another end user
            {"tenant_id": 2},  # another tenant
        ],
    )
    async def test_other_callers_are_refused(self, storage, api_conversation, subject_kwargs):
        with pytest.raises(HTTPException) as caught:
            await ChatSessionService.resolve_subject_attachment_url("c1", "f1", self._subject(**subject_kwargs))
        assert caught.value.status_code == 404

        storage.get_share_link.assert_not_awaited()

    async def test_platform_conversation_is_not_reachable_through_the_open_api(self, storage, conversation):
        # Owned by a natural person on the platform, not by any Open API caller.
        with pytest.raises(HTTPException) as caught:
            await ChatSessionService.resolve_subject_attachment_url("c1", "f1", self._subject())
        assert caught.value.status_code == 404

        storage.get_share_link.assert_not_awaited()
