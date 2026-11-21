"""A historical creator and known IDs never authorize another tenant's data."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.admin.application import request_admission
from bisheng.api.services import knowledge_imp
from bisheng.chat_session.api.endpoints import chat as chat_endpoints
from bisheng.chat_session.domain.repositories import moderation_repository
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.request_scope import RequestScope, inherit_scope
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    tenant_execution_scope,
    visible_tenant_ids,
)
from bisheng.database.models import message as message_module
from bisheng.database.models import session as session_module
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.knowledge.api.endpoints import knowledge as knowledge_endpoints
from bisheng.knowledge.application.deletion_compatibility import delete_legacy_files
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models import knowledge_file as file_module
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    QAKnoweldgeDao,
    QAKnowledge,
    QAKnowledgeUpsert,
    QAStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories import runtime_identity as identity_repository
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter

TENANTS = (1, 60, 70)
OWNER = 849


@pytest.fixture
async def migrated(tmp_path, monkeypatch, isolated_tenant_filter):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    async_engine = create_async_engine(url.replace("sqlite:", "sqlite+aiosqlite:"))
    models = (Knowledge, KnowledgeFile, QAKnowledge, ChatMessage, MessageSession, User, Tenant, UserTenant)
    for model in models:
        model.__table__.create(engine)
    with bypass_tenant_filter(), Session(engine) as db:
        db.add(User(user_id=OWNER, user_name="migrated", password="fixture-only"))
        db.add(UserTenant(id=1, user_id=OWNER, tenant_id=1, is_active=1, status="active"))
        for tenant in TENANTS:
            db.add(Tenant(id=tenant, tenant_code=f"tenant-{tenant}", tenant_name=f"Tenant {tenant}"))
            db.add(Knowledge(id=tenant, tenant_id=tenant, user_id=OWNER, name=f"kb-{tenant}", type=1))
            db.add(Knowledge(id=1000 + tenant, tenant_id=tenant, user_id=OWNER, name=f"space-{tenant}", type=3))
            db.add(KnowledgeFile(id=tenant, tenant_id=tenant, user_id=OWNER, knowledge_id=tenant, file_name="old.txt"))
            db.add(
                QAKnowledge(
                    id=tenant,
                    tenant_id=tenant,
                    user_id=OWNER,
                    knowledge_id=tenant,
                    questions=["old"],
                    answers='["answer"]',
                )
            )
            db.add(
                MessageSession(
                    chat_id=f"chat-{tenant}",
                    tenant_id=tenant,
                    user_id=OWNER,
                    flow_id="workflow",
                    flow_type=10,
                    name="old",
                )
            )
            db.add(
                ChatMessage(
                    id=tenant,
                    tenant_id=tenant,
                    user_id=OWNER,
                    chat_id=f"chat-{tenant}",
                    flow_id="workflow",
                    is_bot=False,
                    type="human",
                    category="question",
                    message="old",
                )
            )
        db.commit()

    @contextmanager
    def sync_session():
        with Session(engine) as db:
            yield db

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            yield db

    for module in (knowledge_module, file_module, message_module, session_module):
        monkeypatch.setattr(module, "get_sync_db_session", sync_session)
        monkeypatch.setattr(module, "get_async_db_session", async_session)
    monkeypatch.setattr(moderation_repository, "get_sync_db_session", sync_session)
    monkeypatch.setattr(identity_repository, "get_async_db_session", async_session)
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    user = SimpleNamespace(user_id=OWNER, user_name="migrated", tenant_id=60, is_global_super=False, token_version=0)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[chat_endpoints.header_share_token_parser] = lambda: None

    @app.exception_handler(BaseErrorCode)
    async def domain_error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    inherit_scope(chat_endpoints.router, RequestScope.PERSONAL)
    inherit_scope(knowledge_endpoints.router, RequestScope.TENANT)
    app.include_router(chat_endpoints.router, prefix="/api/v1")
    app.include_router(knowledge_endpoints.router, prefix="/api/v1")
    request_admission.install_request_admission(app)
    permission = Mock()
    monkeypatch.setattr(
        knowledge_endpoints.KnowledgeService.permission_service, "ensure_knowledge_write_sync", permission
    )
    vectors = Mock()
    monkeypatch.setattr(knowledge_imp, "delete_vector_data", vectors)
    monkeypatch.setattr(knowledge_imp, "QA_save_knowledge", lambda knowledge, qa: qa)
    monkeypatch.setattr(knowledge_endpoints, "_audit_qa", Mock())
    monkeypatch.setattr(knowledge_endpoints.telemetry_service, "log_event_sync", Mock())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, user=user, db=sync_session, vectors=vectors, permission=permission)
    await async_engine.dispose()
    engine.dispose()


def assert_denied(response):
    assert response.status_code in (403, 404) or response.json()["status_code"] in (403, 404), response.text


@pytest.mark.parametrize("tenant", TENANTS)
async def test_message_delete_cannot_follow_creator_to_another_tenant(migrated, tenant):
    migrated.user.tenant_id = tenant
    for foreign in set(TENANTS) - {tenant}:
        await migrated.client.delete(f"/api/v1/chat/message/{foreign}")
    with bypass_tenant_filter(), migrated.db() as db:
        assert {row.id for row in db.exec(select(ChatMessage)).all()} == set(TENANTS)
    response = await migrated.client.delete(f"/api/v1/chat/message/{tenant}")
    assert response.status_code == 200
    with bypass_tenant_filter(), migrated.db() as db:
        assert {row.id for row in db.exec(select(ChatMessage)).all()} == set(TENANTS) - {tenant}


@pytest.mark.parametrize("old_home,new_home", [(1, 60), (60, 70), (70, 1)])
async def test_an_open_browser_socket_cannot_keep_using_its_old_tenant(migrated, monkeypatch, old_home, new_home):
    from bisheng.api.v1 import assistant as endpoint
    from bisheng.common.chat.manager import ChatManager
    from bisheng.common.chat.types import WorkType
    from bisheng.common.errcode.permission import PermissionDeniedError

    migrated.user.tenant_id = old_home
    with bypass_tenant_filter(), migrated.db() as db:
        db.get(UserTenant, 1).tenant_id = old_home
        db.commit()
    manager = ChatManager()
    manager._has_use_action = AsyncMock(return_value=True)  # A historical grant still exists.
    client = SimpleNamespace(handle_message=AsyncMock())
    captured = {}

    async def capture_connection(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(endpoint, "require_business_action", AsyncMock())
    monkeypatch.setattr(endpoint.chat_manager, "dispatch_client", capture_connection)
    await endpoint.chat(assistant_id="old-app", websocket=SimpleNamespace(close=AsyncMock()), login_user=migrated.user)

    async def send():
        return await manager._dispatch_message(
            client,
            {"action": "input"},
            login_user=migrated.user,
            work_type=WorkType.GPTS,
            client_id="old-app",
            message_admission=captured.get("message_admission"),
        )

    with tenant_execution_scope(old_home):
        assert await send()
        with bypass_tenant_filter(), migrated.db() as db:
            db.get(UserTenant, 1).tenant_id = new_home
            db.commit()
        with pytest.raises(PermissionDeniedError):
            await send()
    manager._has_use_action.assert_awaited_once()
    client.handle_message.assert_awaited_once_with({"action": "input"})


@pytest.mark.parametrize(
    "path,method,payload",
    [
        ("/chat/history?chat_id=chat-1&flow_id=workflow", "get", None),
        ("/chat/info?chat_id=chat-1", "get", None),
        ("/chat/conversation/rename", "post", {"conversationId": "chat-1", "name": "stolen"}),
        ("/chat/chat-1", "delete", None),
        ("/chat/chat-1/files/known/url", "get", None),
        ("/chat/message/1", "put", {"message": "stolen"}),
    ],
)
@pytest.mark.parametrize("tenant", TENANTS)
async def test_known_conversation_ids_do_not_reopen_old_tenant(migrated, path, method, payload, tenant):
    migrated.user.tenant_id = tenant
    foreign = next(other for other in TENANTS if other != tenant)
    path = path.replace("chat-1", f"chat-{foreign}").replace("message/1", f"message/{foreign}")
    if payload and "conversationId" in payload:
        payload = {**payload, "conversationId": f"chat-{foreign}"}
    response = await migrated.client.request(method, f"/api/v1{path}", json=payload)
    if method == "delete":
        # Deleting an invisible session is deliberately an idempotent no-op.
        assert response.status_code == 200
    else:
        assert_denied(response)
    with bypass_tenant_filter(), migrated.db() as db:
        assert db.get(ChatMessage, foreign).message == "old"
        session = db.exec(select(MessageSession).where(MessageSession.chat_id == f"chat-{foreign}")).one()
        assert session.name == "old" and not session.is_delete


@pytest.mark.parametrize("tenant", TENANTS)
async def test_mixed_qa_delete_rejects_before_any_side_effect(migrated, tenant):
    migrated.user.tenant_id = tenant
    response = await migrated.client.request("DELETE", "/api/v1/knowledge/qa/delete", json={"ids": list(TENANTS)})
    assert_denied(response)
    migrated.vectors.assert_not_called()
    migrated.permission.assert_not_called()
    with bypass_tenant_filter(), migrated.db() as db:
        assert {row.id for row in db.exec(select(QAKnowledge)).all()} == set(TENANTS)


async def test_own_qa_delete_still_works(migrated):
    response = await migrated.client.request("DELETE", "/api/v1/knowledge/qa/delete", json={"ids": [60, 60]})
    assert response.status_code == 200 and response.json()["status_code"] == 200
    migrated.vectors.assert_called_once()
    with bypass_tenant_filter(), migrated.db() as db:
        assert {row.id for row in db.exec(select(QAKnowledge)).all()} == {1, 70}


@pytest.mark.parametrize("ids", [[], [1], [70], [60, 999], [60, 61]])
@pytest.mark.parametrize("operation", ["delete", "append"])
async def test_qa_batch_requires_every_id_and_one_authorized_parent(migrated, ids, operation):
    with bypass_tenant_filter(), migrated.db() as db:
        db.add(Knowledge(id=61, tenant_id=60, user_id=OWNER, name="other kb", type=1))
        db.add(
            QAKnowledge(id=61, tenant_id=60, user_id=OWNER, knowledge_id=61, questions=["other"], answers='["other"]')
        )
        db.commit()
    payload = {"ids": ids}
    if operation == "append":
        payload["question"] = "stolen"
    response = await migrated.client.request(
        "DELETE" if operation == "delete" else "POST", f"/api/v1/knowledge/qa/{operation}", json=payload
    )
    assert_denied(response)
    migrated.permission.assert_not_called()
    migrated.vectors.assert_not_called()
    with bypass_tenant_filter(), migrated.db() as db:
        rows = db.exec(select(QAKnowledge)).all()
        assert len(rows) == 4 and all("stolen" not in row.questions for row in rows)


async def test_qa_create_api_ignores_a_supplied_foreign_tenant(migrated):
    response = await migrated.client.post(
        "/api/v1/knowledge/qa/add",
        json={"knowledge_id": 60, "tenant_id": 1, "user_id": 123, "questions": ["new"], "answers": ["answer"]},
    )
    assert response.status_code == 200 and response.json()["status_code"] == 200
    with bypass_tenant_filter(), migrated.db() as db:
        created = db.exec(select(QAKnowledge).where(QAKnowledge.id.not_in(TENANTS))).one()
        assert (created.tenant_id, created.knowledge_id, created.user_id) == (60, 60, OWNER)


async def test_qa_add_cannot_edit_an_old_tenant_id_through_an_own_parent(migrated):
    response = await migrated.client.post(
        "/api/v1/knowledge/qa/add",
        json={"id": 1, "knowledge_id": 60, "tenant_id": 1, "questions": ["stolen"], "answers": ["stolen"]},
    )
    assert_denied(response)
    migrated.vectors.assert_not_called()
    with bypass_tenant_filter(), migrated.db() as db:
        assert db.get(QAKnowledge, 1).questions == ["old"]


async def test_own_qa_append_deduplicates_ids_and_retains_ownership(migrated):
    response = await migrated.client.post("/api/v1/knowledge/qa/append", json={"ids": [60, 60], "question": "new"})
    assert response.status_code == 200 and response.json()["status_code"] == 200
    with bypass_tenant_filter(), migrated.db() as db:
        own = db.get(QAKnowledge, 60)
        assert (own.tenant_id, own.knowledge_id, own.questions) == (60, 60, ["old", "new"])
        assert db.get(QAKnowledge, 1).questions == ["old"]


async def test_qa_status_switch_refuses_a_known_old_tenant_id(migrated):
    assert_denied(await migrated.client.post("/api/v1/knowledge/qa/status_switch", json={"id": 1, "status": 0}))
    migrated.permission.assert_not_called()


@pytest.mark.parametrize("tenant", TENANTS)
@pytest.mark.parametrize(
    "operation", ["info", "list", "update", "delete", "preview", "download", "rename_file", "delete_file"]
)
async def test_space_and_file_ids_are_rejected_before_historical_permissions(migrated, tenant, operation):
    migrated.user.tenant_id = tenant
    service = KnowledgeSpaceService(None, migrated.user)
    with tenant_execution_scope(tenant):
        for foreign in set(TENANTS) - {tenant}:
            calls = {
                "info": lambda foreign=foreign: service.get_space_info(1000 + foreign),
                "list": lambda foreign=foreign: service.list_space_children(1000 + foreign),
                "update": lambda foreign=foreign: service.update_knowledge_space(1000 + foreign, name="stolen"),
                "delete": lambda foreign=foreign: service.delete_space(1000 + foreign),
                "preview": lambda foreign=foreign: service.get_file_preview(foreign),
                "download": lambda foreign=foreign: service.get_file_download(foreign),
                "rename_file": lambda foreign=foreign: service.rename_file(foreign, "stolen.txt"),
                "delete_file": lambda foreign=foreign: service.delete_file(foreign),
            }
            # No permission adapter or external storage is supplied: resolving
            # an invisible business target must stop before either is reached.
            with pytest.raises(BaseErrorCode):
                await calls[operation]()
    with bypass_tenant_filter(), migrated.db() as db:
        for foreign in set(TENANTS) - {tenant}:
            assert db.get(Knowledge, 1000 + foreign).name == f"space-{foreign}"
            assert db.get(KnowledgeFile, foreign).file_name == "old.txt"


async def test_explicit_maintenance_bypass_still_allows_a_scoped_repair(migrated):
    with tenant_execution_scope(60), bypass_tenant_filter():
        ChatMessageDao.update_message(1, OWNER, "repaired")
    with bypass_tenant_filter(), migrated.db() as db:
        assert db.get(ChatMessage, 1).message == "repaired"


async def test_bulk_write_without_tenant_context_fails_before_mutation(migrated, monkeypatch):
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    token = current_tenant_id.set(None)
    try:
        with pytest.raises(NoTenantContextError):
            ChatMessageDao.delete_by_message_id(OWNER, 1)
        with pytest.raises(NoTenantContextError):
            KnowledgeFileDao.delete_batch([1])
    finally:
        current_tenant_id.reset(token)
    with bypass_tenant_filter(), migrated.db() as db:
        assert db.get(ChatMessage, 1) is not None
        assert db.get(KnowledgeFile, 1) is not None


@pytest.mark.parametrize("tenant", TENANTS)
async def test_bulk_message_and_session_writes_preserve_foreign_rows(migrated, tenant):
    with tenant_execution_scope(tenant), wide_visibility():
        for foreign in set(TENANTS) - {tenant}:
            chat = f"chat-{foreign}"
            ChatMessageDao.update_message(foreign, OWNER, "stolen")
            ChatMessageDao.update_message_copied(foreign, 1)
            ChatMessageDao.update_message_mark(chat, 9)
            ChatMessageDao.delete_by_user_chat_id(OWNER, chat)
            await ChatMessageDao.adelete_by_user_chat_id(OWNER, chat)
            MessageSessionDao.update_sensitive_status(chat, SensitiveStatus.VIOLATIONS)
            MessageSessionDao.add_like_count(chat, 1)
            MessageSessionDao.add_dislike_count(chat, 1)
            MessageSessionDao.add_copied_count(chat, 1)
            MessageSessionDao.update_session_name_sync(chat, "stolen")
            await MessageSessionDao.update_session_name(chat, "stolen")
            await MessageSessionDao.delete_session(chat)
    with bypass_tenant_filter(), migrated.db() as db:
        for foreign in set(TENANTS) - {tenant}:
            message = db.get(ChatMessage, foreign)
            assert message is not None and (message.message, message.copied, message.mark_status) == ("old", 0, 1)
            session = db.exec(select(MessageSession).where(MessageSession.chat_id == f"chat-{foreign}")).one()
            assert (session.name, session.like, session.dislike, session.copied, session.is_delete) == (
                "old",
                0,
                0,
                0,
                False,
            )
            assert session.sensitive_status == SensitiveStatus.PASS.value


@pytest.mark.parametrize("tenant", TENANTS)
async def test_bulk_file_and_qa_writes_preserve_foreign_rows(migrated, tenant):
    foreign = list(set(TENANTS) - {tenant})
    with tenant_execution_scope(tenant), wide_visibility():
        KnowledgeFileDao.update_file_status(foreign, KnowledgeFileStatus.FAILED)
        await KnowledgeFileDao.aupdate_file_status(foreign, KnowledgeFileStatus.FAILED)
        KnowledgeFileDao.update_status_bulk(foreign, KnowledgeFileStatus.FAILED)
        KnowledgeFileDao.delete_batch(foreign)
        await KnowledgeFileDao.adelete_batch(foreign)
        QAKnoweldgeDao.batch_update_status_by_ids(foreign, QAStatus.FAILED)
        for owner in foreign:
            QAKnoweldgeDao.update_status_by_knowledge_id(owner, QAStatus.FAILED)
        QAKnoweldgeDao.delete_batch(foreign)
    with bypass_tenant_filter(), migrated.db() as db:
        for owner in foreign:
            file = db.get(KnowledgeFile, owner)
            assert file is not None and file.status != KnowledgeFileStatus.FAILED.value
            qa = db.get(QAKnowledge, owner)
            assert qa is not None and qa.status == 1


@pytest.mark.parametrize("tenant", TENANTS)
async def test_legacy_file_delete_rejects_a_partially_visible_batch(migrated, tenant):
    migrated.user.tenant_id = tenant
    with tenant_execution_scope(tenant), pytest.raises(HTTPException) as error:
        await delete_legacy_files(request=None, identity=migrated.user, file_ids=list(TENANTS))
    assert error.value.status_code == 404
    with bypass_tenant_filter(), migrated.db() as db:
        assert {row.id for row in db.exec(select(KnowledgeFile)).all()} == set(TENANTS)


@contextmanager
def wide_visibility():
    token = visible_tenant_ids.set(frozenset(TENANTS))
    try:
        yield
    finally:
        visible_tenant_ids.reset(token)


async def test_qa_create_derives_tenant_from_authorized_parent(migrated):
    with tenant_execution_scope(60):
        parent = KnowledgeDao.query_by_id(60)
        data = QAKnowledgeUpsert(tenant_id=1, user_id=OWNER, knowledge_id=60, questions=["new"], answers=["answer"])
        created = knowledge_imp.add_qa(parent, data)
        assert (created.tenant_id, created.knowledge_id) == (60, 60)


async def test_qa_update_cannot_substitute_a_different_parent(migrated):
    with bypass_tenant_filter(), migrated.db() as db:
        db.add(Knowledge(id=61, tenant_id=60, user_id=OWNER, name="other kb", type=1))
        db.add(
            QAKnowledge(id=61, tenant_id=60, user_id=OWNER, knowledge_id=61, questions=["other"], answers='["other"]')
        )
        db.commit()
    with tenant_execution_scope(60), pytest.raises(BaseErrorCode):
        knowledge_imp.add_qa(
            KnowledgeDao.query_by_id(60),
            QAKnowledgeUpsert(id=61, knowledge_id=60, questions=["stolen"], answers=["stolen"]),
        )
    migrated.vectors.assert_not_called()
    with bypass_tenant_filter(), migrated.db() as db:
        assert db.get(QAKnowledge, 61).questions == ["other"]
