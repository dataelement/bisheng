"""Preserve anonymous v2 draft behavior without exposing another session's data."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.public_endpoints import PublicApplicationOfflineError
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.main import handle_http_exception
from bisheng.public_endpoints.api.endpoints import chat
from bisheng.public_endpoints.api.exception_handlers import register_public_exception_handlers

FLOW_ID = "816acf819f254de68cf34779a7586621"
CHAT_ID = "419f82f46fba51f7d5cee9662b761787"


def _session(**updates):
    values = {
        "chat_id": CHAT_ID,
        "flow_id": FLOW_ID,
        "flow_name": "Published workflow",
        "flow_type": 10,
        "user_id": 8,
        "tenant_id": 3,
        "api_subject_type": "public_v3",
        "is_delete": False,
        "name": "Generated title",
    }
    values.update(updates)
    return MessageSession(**values)


@pytest.fixture
def publication(monkeypatch):
    state = SimpleNamespace(session=None, error=None, resources=[])
    subject = SessionSubject.public_v3(tenant_id=3, operator_user_id=8, resource_id=FLOW_ID)

    @asynccontextmanager
    async def execution(resource_id):
        state.resources.append(resource_id)
        if state.error is not None:
            raise state.error
        yield SimpleNamespace(session_subject=subject)

    monkeypatch.setattr(chat, "public_application_execution", execution)
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(side_effect=lambda chat_id: state.session))
    state.history = AsyncMock(return_value=[{"id": 7, "message": "Existing answer"}])
    monkeypatch.setattr(ChatSessionService, "get_chat_history", state.history)
    state.sleep = AsyncMock()
    monkeypatch.setattr(chat, "asyncio", SimpleNamespace(sleep=state.sleep))
    return state


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(chat.router, prefix="/api/v3")
    app.add_exception_handler(HTTPException, handle_http_exception)
    register_public_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _history(client, **params):
    return await client.get(
        "/api/v3/chat/history",
        params={"flow_id": FLOW_ID, "chat_id": CHAT_ID, "page_size": 40, "id": "", **params},
    )


async def test_draft_history_returns_success_and_empty_list(client, publication):
    response = await _history(client)

    assert response.status_code == 200
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": []}
    assert publication.resources == [FLOW_ID]
    publication.history.assert_not_awaited()


@pytest.mark.parametrize("messages", [[], [{"id": 7, "message": "Existing answer"}]])
async def test_existing_public_session_preserves_history_and_pagination(client, publication, messages):
    publication.session = _session()
    publication.history.return_value = messages

    response = await _history(client, id="12", page_size=10)

    assert response.json()["status_code"] == 200
    assert response.json()["data"] == messages
    publication.history.assert_awaited_once_with(CHAT_ID, FLOW_ID, "12", 10)


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": 4},
        {"flow_id": "another-flow"},
        {"api_subject_type": None},
        {"api_subject_type": "service_account", "api_subject_id": 8},
        {"is_delete": True},
    ],
)
async def test_existing_inaccessible_history_is_not_treated_as_a_draft(client, publication, updates):
    publication.session = _session(**updates)

    response = await _history(client)

    assert response.json()["status_code"] == 404
    publication.history.assert_not_awaited()


async def test_draft_history_still_requires_a_published_application(client, publication):
    publication.error = PublicApplicationOfflineError()

    response = await _history(client)

    assert response.status_code == 404
    assert response.json()["status_code"] == 26102
    publication.history.assert_not_awaited()


async def test_missing_title_returns_legacy_default_after_creation_grace_period(client, publication):
    response = await client.post("/api/v3/chat/gen_title", json={"conversationId": CHAT_ID})

    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"] == {"title": "New Chat"}
    publication.sleep.assert_awaited_once_with(5)
    assert publication.resources == []


@pytest.mark.parametrize("title", ["Generated title", "New Chat", ""])
async def test_title_created_during_grace_period_is_returned(client, publication, title):
    async def finish_creation(_delay):
        publication.session = _session(name=title)

    publication.sleep.side_effect = finish_creation
    response = await client.post("/api/v3/chat/gen_title", json={"conversationId": CHAT_ID})

    assert response.json()["status_code"] == 200
    assert response.json()["data"] == {"title": title or "New Chat"}
    assert publication.resources == [FLOW_ID]


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": 4},
        {"flow_id": "another-flow"},
        {"api_subject_type": None},
        {"api_subject_type": "service_account", "api_subject_id": 8},
        {"is_delete": True},
    ],
)
async def test_existing_inaccessible_title_does_not_use_missing_session_fallback(client, publication, updates):
    publication.session = _session(**updates)

    response = await client.post("/api/v3/chat/gen_title", json={"conversationId": CHAT_ID})

    assert response.json()["status_code"] == 404
    assert "Generated title" not in response.text


async def test_existing_title_still_requires_a_published_application(client, publication):
    publication.session = _session()
    publication.error = PublicApplicationOfflineError()

    response = await client.post("/api/v3/chat/gen_title", json={"conversationId": CHAT_ID})

    assert response.status_code == 404
    assert response.json()["status_code"] == 26102


@pytest.mark.parametrize("header", ["X-On-Behalf-Of", "X-End-User"])
async def test_missing_title_ignores_identity_headers(client, publication, header):
    response = await client.post("/api/v3/chat/gen_title", json={"conversationId": CHAT_ID}, headers={header: "123"})

    assert response.status_code == 200
    assert response.json()["data"] == {"title": "New Chat"}
    publication.sleep.assert_awaited_once_with(5)
