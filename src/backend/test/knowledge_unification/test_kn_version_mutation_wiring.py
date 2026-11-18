"""Original HTTP/DI/service writes use the actual short-transaction version app."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError
from bisheng.knowledge.api import dependencies
from bisheng.knowledge.api.endpoints import knowledge_version as api
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services import knowledge_version_service as module
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import KnowledgeAuditTelemetryService
from test.knowledge_unification import test_kn_version_mutation_repository as native_tests

native = native_tests.native
database = native_tests.database


@pytest.fixture
async def wired(database, monkeypatch):
    sessions = []
    # HTTP mutations require a published business resource, unlike raw repository fixtures.
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 9700).values(state=1))

    @asynccontextmanager
    async def fresh():
        async with AsyncSession(database.engine) as session:
            sessions.append(session)
            yield session

    monkeypatch.setattr(dependencies, "get_async_db_session", fresh)
    settings = SimpleNamespace(version_management=SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        module, "bisheng_settings", SimpleNamespace(async_get_knowledge=AsyncMock(return_value=settings))
    )
    audit_link, audit_primary = Mock(), Mock()
    monkeypatch.setattr(KnowledgeAuditTelemetryService, "audit_link_file_version", audit_link)
    monkeypatch.setattr(KnowledgeAuditTelemetryService, "audit_set_primary_version", audit_primary)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    # Preflight authorization uses real repository reads in a separate request
    # session; the application still owns exactly one fresh mutation session.
    from bisheng.knowledge.domain.models import knowledge as knowledge_model
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )

    @asynccontextmanager
    async def read_session():
        async with AsyncSession(database.engine) as session:
            yield session

    monkeypatch.setattr(knowledge_model, "get_async_db_session", read_session)
    permission = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", permission)

    class ReadPort:
        def __init__(self, repository_type):
            self.repository_type = repository_type

        def __getattr__(self, name):
            async def read(*args, **kwargs):
                async with read_session() as session:
                    return await getattr(self.repository_type(session), name)(*args, **kwargs)

            return read

    service = await dependencies.get_knowledge_version_service(
        request=Request({"type": "http", "headers": []}),
        login_user=user,
        doc_repo=ReadPort(KnowledgeDocumentRepositoryImpl),
        version_repo=ReadPort(KnowledgeDocumentVersionRepositoryImpl),
        knowledge_file_repo=ReadPort(KnowledgeFileRepositoryImpl),
        read_service=object(),
    )
    yield SimpleNamespace(
        permission=permission,
        database=database,
        service=service,
        user=user,
        sessions=sessions,
        factory=fresh,
        settings=settings,
        audit_link=audit_link,
        audit_primary=audit_primary,
    )


async def test_actual_version_di_binds_original_feature_and_independent_session_factory(wired):
    application = wired.service.version_mutation_application
    assert application.sessions is wired.factory
    assert application.enabled == wired.service._require_version_management_enabled
    assert not wired.sessions


async def invoke(wired, operation):
    if operation == "link":
        return await wired.service.link_file_to_document(101, 20)
    if operation == "merge":
        return await wired.service.merge_source_document_into_current(201, 10)
    return await wired.service.set_primary_version(2001)


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_original_http_writes_commit_one_complete_chain_and_keep_response_and_audit(wired, operation):
    before = await native_tests.snapshot(wired.database)
    server = FastAPI()
    server.include_router(api.router, prefix="/api/v1")
    server.dependency_overrides[dependencies.get_knowledge_version_service] = lambda: wired.service
    routes = {
        "link": ("document/link", {"knowledge_file_id": 101, "target_document_id": 20}),
        "merge": ("version/merge", {"current_knowledge_file_id": 201, "source_document_id": 10}),
        "primary": ("version/2001/set-primary", None),
    }
    path, body = routes[operation]
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://offline") as client:
        response = await client.post("/api/v1/knowledge/space/" + path, json=body)
    assert response.status_code == 200
    expected = {"document_id": 20}
    expected["new_primary_version_no" if operation == "primary" else "new_version_no"] = (
        1 if operation == "primary" else 4
    )
    assert response.json()["data"] == expected
    assert len(wired.sessions) == 1 and not wired.sessions[0].in_transaction()
    after = await native_tests.snapshot(wired.database)
    versions = [row for row in after["knowledge_document_version"] if row["document_id"] == 20]
    primary = [row for row in versions if row["is_primary"]]
    assert len(primary) == 1
    document = next(row for row in after["knowledge_document"] if row["id"] == 20)
    assert document["primary_version_id"] == primary[0]["id"]
    incoming = 201 if operation == "primary" else 101
    for row in after["knowledgefile"]:
        old = next(old for old in before["knowledgefile"] if old["id"] == row["id"])
        assert {key: value for key, value in row.items() if key not in {"similar_status", "update_time"}} == {
            key: value for key, value in old.items() if key not in {"similar_status", "update_time"}
        }
        if row["id"] != incoming or operation == "primary":
            assert row == old
    audit = wired.audit_primary if operation == "primary" else wired.audit_link
    audit.assert_called_once()
    assert audit.call_args.args[0] is wired.user
    assert audit.call_args.args[2:] == (9700, "private-name", 1 if operation == "primary" else 4)


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_disabled_original_switch_precedes_any_application_session_and_audit(wired, operation):
    before = await native_tests.snapshot(wired.database)
    wired.settings.version_management.enabled = False
    with pytest.raises(VersionManagementDisabledError):
        await invoke(wired, operation)
    assert not wired.sessions and await native_tests.snapshot(wired.database) == before
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_locked_real_rebuilding_space_keeps_entire_chain_and_audit_unchanged(wired, operation):
    async with wired.database.engine.begin() as connection:
        await connection.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 9700).values(state=3))
    before = await native_tests.snapshot(wired.database)
    with pytest.raises(KnowledgeProcessingConflictError):
        await invoke(wired, operation)
    assert await native_tests.snapshot(wired.database) == before
    assert len(wired.sessions) == 1 and not wired.sessions[0].in_transaction()
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_edit_denial_precedes_native_transaction_and_preserves_database(wired, operation):
    from fastapi import HTTPException

    before = await native_tests.snapshot(wired.database)
    wired.permission.side_effect = HTTPException(status_code=403, detail="edit denied")
    with pytest.raises(HTTPException) as error:
        await invoke(wired, operation)
    assert error.value.status_code == 403
    assert not wired.sessions
    assert await native_tests.snapshot(wired.database) == before
    wired.permission.assert_awaited_once_with(
        wired.user, resource_type="knowledge_space", resource_id=9700, action="edit"
    )
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


async def test_commit_ack_loss_propagates_original_exception_without_false_audit_or_relink_retry(wired):
    before = await native_tests.snapshot(wired.database)
    failure = RuntimeError("commit ACK unknown")
    calls = []

    @asynccontextmanager
    async def lost_ack():
        async with AsyncSession(wired.database.engine) as session:

            def committed(_session):
                calls.append(1)
                raise failure

            sa.event.listen(session.sync_session, "after_commit", committed)
            yield session

    wired.service.version_mutation_application.sessions = lost_ack
    with pytest.raises(RuntimeError) as caught:
        await wired.service.link_file_to_document(101, 20)
    assert caught.value is failure and calls == [1]
    after = await native_tests.snapshot(wired.database)
    versions = [row for row in after["knowledge_document_version"] if row["document_id"] == 20]
    old_count = sum(row["document_id"] == 20 for row in before["knowledge_document_version"])
    assert len(versions) == old_count + 1 and len([row for row in versions if row["is_primary"]]) == 1
    assert next(row for row in versions if row["is_primary"])["knowledge_file_id"] == 101
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()
