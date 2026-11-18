"""AC-60..64: old Cookie-only callbacks with real routes, services and SQLite."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Load production composition first, including its actual endpoint scopes.
    from bisheng.admin.application import request_admission
    from bisheng.api.services.audit_log import AuditLogService
    from bisheng.chat_session.domain import chat
    from bisheng.chat_session.domain.repositories import moderation_repository
    from bisheng.chat_session.domain.services import moderation_scope
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import tenant_filter
    from bisheng.database.models import flow as flows
    from bisheng.database.models import message
    from bisheng.database.models import session as conversations
    from bisheng.database.models.assistant import Assistant
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.tenant import Tenant
    from bisheng.main import app as production
    from bisheng.permission.application import business_authorization

    engine = create_engine(f"sqlite:///{tmp_path / 'moderation.db'}")
    SQLModel.metadata.create_all(
        engine,
        tables=[row.__table__ for row in (Tenant, Flow, Assistant, message.ChatMessage, conversations.MessageSession)],
    )
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables | {"flow", "assistant", "chatmessage", "message_session"},
    )

    @contextmanager
    def database():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    for module in (moderation_repository, message, conversations, flows):
        monkeypatch.setattr(module, "get_sync_db_session", database)
    monkeypatch.setattr(conversations.UserGroupDao, "get_user_group", lambda _: [])
    monkeypatch.setattr(conversations, "stamp_session", lambda _: None)
    monkeypatch.setattr(AuditLogService, "create_chat_workflow", lambda *args: None)
    monkeypatch.setattr(AuditLogService, "create_chat_assistant", lambda *args: None)
    monkeypatch.setattr(chat.telemetry_service, "log_event_sync", lambda **kwargs: None)
    permission = AsyncMock()
    monkeypatch.setattr(business_authorization, "require_business_action", permission)
    user = SimpleNamespace(user_id=7, tenant_id=1, user_name="tester", is_global_super=True)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    selection = AsyncMock(side_effect=AssertionError("Legacy callback must not read current management selection"))
    monkeypatch.setattr(request_admission, "request_target", selection)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    for route in production.routes:
        if route.path in {"/api/v1/chat/message", "/api/v1/chat/message/{message_id}"}:
            app.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.return_resp_instance().model_dump())

    request_admission.install_request_admission(app)
    with bypass_tenant_filter(), database() as db:
        db.add_all([Tenant(id=tid, tenant_code=f"test-{tid}", tenant_name=f"Tenant {tid}") for tid in (1, 60, 65)])
        db.add(Flow(id="flow-b", name="B workflow", tenant_id=60, user_id=8, flow_type=10))
        db.add(Assistant(id="shared-root", name="Shared", tenant_id=1, user_id=8, is_shared=True))
        db.add_all(
            [
                conversations.MessageSession(
                    chat_id="existing", flow_id="flow-b", flow_type=10, tenant_id=60, user_id=7
                ),
                conversations.MessageSession(
                    chat_id="foreign", flow_id="flow-b", flow_type=10, tenant_id=60, user_id=8
                ),
                conversations.MessageSession(
                    chat_id="gone", flow_id="flow-b", flow_type=10, tenant_id=60, user_id=7, is_delete=True
                ),
                conversations.MessageSession(
                    chat_id="api",
                    flow_id="flow-b",
                    flow_type=10,
                    tenant_id=60,
                    user_id=7,
                    api_subject_type="service_account",
                ),
            ]
        )
        db.add_all(
            [
                message.ChatMessage(
                    id=11,
                    tenant_id=60,
                    user_id=7,
                    chat_id="existing",
                    flow_id="flow-b",
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="original",
                ),
                message.ChatMessage(
                    id=12,
                    tenant_id=60,
                    user_id=8,
                    chat_id="foreign",
                    flow_id="flow-b",
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="other",
                ),
                message.ChatMessage(
                    id=13,
                    tenant_id=60,
                    user_id=7,
                    chat_id="missing",
                    flow_id="flow-b",
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="orphan",
                ),
                message.ChatMessage(
                    id=14,
                    tenant_id=65,
                    user_id=7,
                    chat_id="existing",
                    flow_id="flow-b",
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="conflict",
                ),
                message.ChatMessage(
                    id=15,
                    tenant_id=60,
                    user_id=7,
                    chat_id="api",
                    flow_id="flow-b",
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="api",
                ),
            ]
        )
        db.commit()
    yield SimpleNamespace(
        app=app,
        user=user,
        db=database,
        permission=permission,
        selection=selection,
        scope=moderation_scope,
        messages=message.ChatMessage,
        sessions=conversations.MessageSession,
    )
    engine.dispose()


def result_code(response):
    return response.json().get("status_code", response.status_code)


def body(chat_id="existing", flow_id="flow-b"):
    return {"chat_id": chat_id, "flow_id": flow_id, "human_message": "question", "answer_message": "blocked"}


async def test_cookie_only_update_preserves_original_tenant_after_switch(setup):
    """AC-61/62/64: target header and current selection are irrelevant to durable writes."""
    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, management_tenant_scope

    before = get_current_tenant_id()
    with management_tenant_scope(65):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/chat/message/11", cookies={"access_token_cookie": "old-cookie"}, json={"message": "safe"}
            )
        assert get_current_tenant_id() == 65
    assert get_current_tenant_id() == before
    assert result_code(response) == 200
    with bypass_tenant_filter(), setup.db() as db:
        saved = db.get(setup.messages, 11)
        assert (saved.message, saved.tenant_id, saved.user_id) == ("safe", 60, 7)
    setup.selection.assert_not_awaited()


async def test_append_to_existing_session_uses_its_tenant(setup):
    """AC-62: the actor's Home=1 does not move an existing tenant-60 conversation."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/message", json=body())
    assert result_code(response) == 200
    assert {row["tenant_id"] for row in response.json()["data"]} == {60}
    setup.selection.assert_not_awaited()


@pytest.mark.parametrize("is_super,home,resource", [(True, 1, "flow-b"), (False, 60, "shared-root")])
async def test_first_interception_creates_home_owned_records(setup, is_super, home, resource):
    """AC-63: a foreign-owned/shared application never sets the first conversation's tenant."""
    from bisheng.core.context.tenant import bypass_tenant_filter

    setup.user.is_global_super = is_super
    setup.user.tenant_id = home
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/message", json=body("first", resource))
    assert result_code(response) == 200
    assert {row["tenant_id"] for row in response.json()["data"]} == {home}
    with bypass_tenant_filter(), setup.db() as db:
        saved = db.get(setup.sessions, "first")
        assert (saved.tenant_id, saved.user_id, saved.flow_id) == (home, 7, resource)
    setup.permission.assert_awaited_once()
    setup.selection.assert_not_awaited()


@pytest.mark.parametrize("message_id", [12, 13, 14, 15, 999])
async def test_foreign_or_inconsistent_message_is_not_modified(setup, message_id):
    """AC-62: another owner, orphan, conflicting tenant, API subject and missing ID fail closed."""
    from bisheng.core.context.tenant import bypass_tenant_filter

    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.put(f"/api/v1/chat/message/{message_id}", json={"message": "tampered"})
    assert result_code(response) in {403, 404}
    with bypass_tenant_filter(), setup.db() as db:
        record = db.get(setup.messages, message_id)
        assert record is None or record.message != "tampered"


@pytest.mark.parametrize(
    "chat,flow",
    [("foreign", "flow-b"), ("gone", "flow-b"), ("api", "flow-b"), ("existing", "shared-root"), ("missing", "flow-b")],
)
async def test_invalid_session_is_rejected_before_message_insert(setup, chat, flow):
    """AC-62: a supplied chat ID is not ownership or resource-binding evidence."""
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter(), setup.db() as db:
        before = len(db.exec(select(setup.messages)).all())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/message", json=body(chat, flow))
    assert result_code(response) in {403, 404}
    with bypass_tenant_filter(), setup.db() as db:
        assert len(db.exec(select(setup.messages)).all()) == before


@pytest.mark.parametrize("credential", [False, True])
async def test_home_user_and_scoped_credential_cannot_follow_foreign_record(setup, credential):
    """AC-62: ordinary users and independent credentials retain their own data boundary."""
    if credential:
        setup.user._dsh_web_session_tenant_id = 1
    else:
        setup.user.is_global_super = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.put("/api/v1/chat/message/11", json={"message": "wrong"})
    assert result_code(response) == 403


async def test_first_interception_requires_original_use_permission(setup):
    """AC-63: legacy compatibility never converts resource IDs into an authorization grant."""
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.core.context.tenant import bypass_tenant_filter

    setup.permission.side_effect = UnAuthorizedError.http_exception()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/message", json=body("not-allowed"))
    assert result_code(response) == 403
    with bypass_tenant_filter(), setup.db() as db:
        assert db.get(setup.sessions, "not-allowed") is None
        assert db.exec(select(setup.messages).where(setup.messages.chat_id == "not-allowed")).all() == []


async def test_callback_still_requires_authentication(setup, monkeypatch):
    """AC-61: identity scope is authenticated, never public or Gateway-IP trusted."""
    from fastapi import HTTPException

    from bisheng.admin.application import request_admission

    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(side_effect=HTTPException(401)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.put("/api/v1/chat/message/11", json={"message": "unauthenticated"})
    assert response.status_code == 401


async def test_unknown_historical_tenant_is_not_backfilled(setup, monkeypatch):
    """AC-62/64: missing durable attribution is not silently assigned to Home."""
    from bisheng.chat_session.domain.repositories.moderation_repository import ModerationRepository, ModerationSubject

    monkeypatch.setattr(
        ModerationRepository, "message_subject", lambda _: ModerationSubject(None, 7, "existing", "flow-b")
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.put("/api/v1/chat/message/11", json={"message": "wrong"})
    assert result_code(response) == 19504


async def test_disabled_record_tenant_does_not_accept_writeback(setup, monkeypatch):
    """AC-62: a valid message ID does not bypass a disabled tenant."""
    from bisheng.chat_session.domain.repositories.moderation_repository import ModerationRepository

    monkeypatch.setattr(ModerationRepository, "tenant_status", lambda _: "disabled")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.put("/api/v1/chat/message/11", json={"message": "wrong"})
    assert result_code(response) == 20001


async def test_first_use_check_sees_resource_but_keeps_home_actor(setup):
    """AC-63/64: F048 can resolve a foreign candidate without changing the execution owner."""
    from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids

    async def check(actor, **kwargs):
        assert actor.tenant_id == 1 and get_current_tenant_id() == 1
        assert 60 in get_visible_tenant_ids()
        assert kwargs == {"resource_type": "workflow", "resource_id": "flow-b", "action": "use"}

    setup.permission.side_effect = check
    before = get_visible_tenant_ids()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(setup.app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/message", json=body("checked-first"))
    assert result_code(response) == 200
    assert get_visible_tenant_ids() == before
