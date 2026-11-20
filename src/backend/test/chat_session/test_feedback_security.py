"""Feedback is a private conversation write, never an audit/read entitlement."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bisheng.chat_session.api.endpoints.feedback import router
from bisheng.chat_session.domain.services import chat_message_service as service
from bisheng.common.dependencies.user_deps import UserPayload


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/liked", {"message_id": 1, "liked": 1}),
        ("/chat/copied", {"message_id": 1}),
        ("/chat/comment", {"message_id": 1, "comment": "poc"}),
    ],
)
def test_anonymous_feedback_has_no_effect(monkeypatch, path, payload):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def deny():
        raise HTTPException(status_code=401)

    app.dependency_overrides[UserPayload.get_login_user] = deny
    effect = MagicMock()
    monkeypatch.setattr(service.ChatMessageService, "like_response", effect)
    monkeypatch.setattr(service.ChatMessageService, "mark_copied", effect)
    monkeypatch.setattr(service.ChatMessageService, "comment_on_answer", effect)
    with TestClient(app) as client:
        result = client.post("/api/v1" + path, json=payload)
    assert result.status_code == 401
    effect.assert_not_called()


@pytest.mark.parametrize("kind", ["foreign", "tenant", "public_v3", "service_account", "deleted"])
def test_feedback_rejects_non_personal_session_before_mutation(monkeypatch, kind):
    message = SimpleNamespace(id=1, user_id=11, tenant_id=7, chat_id="chat", liked=0, copied=0)
    session = SimpleNamespace(
        user_id=22 if kind == "foreign" else 11,
        tenant_id=8 if kind == "tenant" else 7,
        api_subject_type=kind if kind in {"public_v3", "service_account"} else None,
        is_delete=kind == "deleted",
        flow_id="app",
    )
    monkeypatch.setattr(service, "_resolve_leaf_tenant_id", lambda _: 7)
    monkeypatch.setattr(service.ChatMessageDao, "get_message_by_id", lambda _: message)
    monkeypatch.setattr(service.MessageSessionDao, "get_one", lambda _: session)
    update, comment = MagicMock(), MagicMock()
    monkeypatch.setattr(service.ChatMessageDao, "update_message_model", update)
    monkeypatch.setattr(service.ChatMessageDao, "update_message_copied", update)
    monkeypatch.setattr(service, "comment_answer", comment)
    actor = SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: True)
    for call in [
        lambda: service.ChatMessageService.like_response(SimpleNamespace(message_id=1, liked=1), actor),
        lambda: service.ChatMessageService.mark_copied(1, actor),
        lambda: service.ChatMessageService.comment_on_answer(1, "poc", actor),
    ]:
        with pytest.raises(HTTPException):
            call()
    update.assert_not_called()
    comment.assert_not_called()


def test_personal_owner_feedback_preserves_counters_and_repeat_behavior(monkeypatch):
    message = SimpleNamespace(id=1, user_id=11, tenant_id=7, chat_id="chat", liked=0, copied=0)
    session = SimpleNamespace(user_id=11, tenant_id=7, api_subject_type=None, is_delete=False)
    monkeypatch.setattr(service, "_resolve_leaf_tenant_id", lambda _: 7)
    monkeypatch.setattr(service.ChatMessageDao, "get_message_by_id", lambda _: message)
    monkeypatch.setattr(service.MessageSessionDao, "get_one", lambda _: session)
    update, copied, like_count, dislike_count, copied_count, comment = (MagicMock() for _ in range(6))
    monkeypatch.setattr(service.ChatMessageDao, "update_message_model", update)

    def mark(*args):
        message.copied = 1
        copied(*args)

    monkeypatch.setattr(service.ChatMessageDao, "update_message_copied", mark)
    monkeypatch.setattr(service.MessageSessionDao, "add_like_count", like_count)
    monkeypatch.setattr(service.MessageSessionDao, "add_dislike_count", dislike_count)
    monkeypatch.setattr(service.MessageSessionDao, "add_copied_count", copied_count)
    monkeypatch.setattr(service, "comment_answer", comment)
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    service.ChatMessageService.like_response(SimpleNamespace(message_id=1, liked=1), actor)
    service.ChatMessageService.like_response(SimpleNamespace(message_id=1, liked=1), actor)
    update.assert_called_once_with(message)
    like_count.assert_called_once_with("chat", 1)
    service.ChatMessageService.mark_copied(1, actor)
    service.ChatMessageService.mark_copied(1, actor)
    copied.assert_called_once_with(1, 1)
    copied_count.assert_called_once_with("chat", 1)
    service.ChatMessageService.comment_on_answer(1, "poc", actor)
    comment.assert_called_once_with(1, "poc")


@pytest.mark.parametrize("field,value", [("tenant_id", 8), ("user_id", 22)])
def test_message_row_itself_must_match_owner(monkeypatch, field, value):
    message = SimpleNamespace(id=1, user_id=11, tenant_id=7, chat_id="chat")
    setattr(message, field, value)
    monkeypatch.setattr(service, "_resolve_leaf_tenant_id", lambda _: 7)
    monkeypatch.setattr(service.ChatMessageDao, "get_message_by_id", lambda _: message)
    monkeypatch.setattr(
        service.MessageSessionDao,
        "get_one",
        lambda _: SimpleNamespace(user_id=11, tenant_id=7, api_subject_type=None, is_delete=False),
    )
    comment = MagicMock()
    monkeypatch.setattr(service, "comment_answer", comment)
    with pytest.raises(HTTPException):
        service.ChatMessageService.comment_on_answer(1, "poc", SimpleNamespace(user_id=11, tenant_id=7))
    comment.assert_not_called()
