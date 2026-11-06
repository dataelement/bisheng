"""T741: both original routers consume the real DI/Facade/Owner/J1 chain."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlmodel import select

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.api.endpoints.knowledge import router as web_router
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.schemas.knowledge_schema import (
    AddKnowledgeMetadataFieldsReq,
    UpdateKnowledgeMetadataFieldsReq,
)
from bisheng.knowledge.domain.services import knowledge_permission_service as permission_module
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.open_endpoints.api.endpoints.knowledge import router as open_router
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.permission.application.identity import PermissionActor
from test.knowledge_unification import test_metadata_job as fixtures
from test.knowledge_unification.test_processing_identity import principal, request_context

store, tenant, business, admission = fixtures.store, fixtures.tenant, fixtures.business, fixtures.admission
processing, application, metadata, owner, flow = (
    fixtures.processing,
    fixtures.application,
    fixtures.metadata,
    fixtures.owner,
    fixtures.flow,
)


@pytest.fixture
def legacy(flow, monkeypatch):
    app = FastAPI()
    app.include_router(web_router, prefix="/api/v1")
    app.include_router(open_router, prefix="/api/v2")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: flow.context.user
    # v2's existing persistence projection has no web-session credential. The
    # actual ambient S/D principal must survive the real business DI graph.
    audit = UserPayload(user_id=11, tenant_id=101, user_role=[])
    app.dependency_overrides[get_open_api_operator_async] = lambda: audit

    async def sessions():
        async with flow.context.sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = sessions
    writer = sys.modules.get("bisheng.knowledge.application.metadata_legacy")
    if writer is not None:
        monkeypatch.setattr(writer, "get_async_db_session", flow.context.sessions, raising=False)
    permission = AsyncMock(return_value=True)
    monkeypatch.setattr(permission_module, "check_business_action", permission)
    retired = AsyncMock(side_effect=AssertionError("SPACE must not dispatch legacy metadata BackgroundTask"))
    monkeypatch.setattr(KnowledgeMetadataService, "update_vectorstore_metadata_field_names", retired)
    monkeypatch.setattr(KnowledgeMetadataService, "delete_vectorstore_metadata_fields", retired)

    @app.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    state = SimpleNamespace(flow=flow, app=app, retired=retired, commits=[])

    def committed(session):
        if session.bind is flow.context.engine.sync_engine:
            state.commits.append(session)

    event.listen(Session, "after_commit", committed)
    try:
        yield state
    finally:
        event.remove(Session, "after_commit", committed)


def command(operation, protocol):
    suffix = {"add": "add_metadata_fields", "rename": "update_metadata_fields", "delete": "delete_metadata_fields"}[
        operation
    ]
    if protocol != "web" and operation == "rename":
        suffix = "modify_metadata_fields"
    body = {"knowledge_id": 40}
    if operation == "add":
        body["metadata_fields"] = [{"field_name": "extra", "field_type": "string", "updated_at": 20}]
    elif operation == "rename":
        body["metadata_fields"] = [{"old_field_name": "note", "new_field_name": "alias"}]
    else:
        body["field_names"] = ["note"]
    return (
        {"add": "POST", "rename": "PUT", "delete": "DELETE"}[operation],
        f"/api/v{1 if protocol == 'web' else 2}/knowledge/{suffix}",
        body,
    )


async def call(legacy, operation="add", protocol="web", *, scope="knowledge:write", empty=False):
    method, url, body = command(operation, protocol)
    if empty:
        body["field_names" if operation == "delete" else "metadata_fields"] = []
    original = principal(delegated=protocol == "D", scopes={scope}) if protocol != "web" else None
    actor = (
        PermissionActor(
            subject_type=original.authorization_subject_type,
            subject_id=original.authorization_subject_id,
            tenant_id=101,
        )
        if original
        else None
    )
    with request_context(actor, original) if original else nullcontext():
        async with AsyncClient(transport=ASGITransport(app=legacy.app), base_url="http://offline") as client:
            response = await client.request(method, url, json=body)
    return response.json()


@pytest.mark.parametrize("protocol", ["web", "S", "D"])
@pytest.mark.parametrize("operation", ["add", "rename", "delete"])
async def test_both_real_di_graphs_accept_schema_and_job_together_without_legacy_task(legacy, protocol, operation):
    result = await call(legacy, operation, protocol)
    assert result["status_code"] == 200
    assert len(legacy.commits) == 1
    async with legacy.flow.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        jobs = (await session.exec(select(KnowledgeProcessingJob))).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.kind == "metadata_schema_change" and job.state == "accepted" and job.total_count == 2
        assert root.metadata_schema_revision == 1 and root.model_config_revision == 0 and root.index_generation == "g0"
        assert job.actor_reference["entry_kind"] == ("web" if protocol == "web" else "open_api")
        credential = job.actor_reference["credential_reference"]
        if protocol != "web":
            assert credential["kind"] == "api_credential" and credential["credential_id"] == 20
            assert credential["identity"]["mode"] == protocol
            assert job.actor_reference["actor"]["subject_type"] == ("user" if protocol == "D" else "service_account")
            assert job.actor_reference["actor"]["subject_id"] == (11 if protocol == "D" else 7)
            assert result["data"] is True
        else:
            assert result["data"]["metadata_fields"] == root.metadata_fields
            assert result["data"]["processing_job"] == {
                "job_id": job.id,
                "state": "accepted",
                "accepted": True,
                "completed": False,
            }
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"
        assert (await session.get(KnowledgeFile, 82)).status == 7
        items = (await session.exec(select(KnowledgeProcessingItem))).all()
        assert {item.version_id for item in items} == {181, 182}
    legacy.retired.assert_not_awaited()


@pytest.mark.parametrize("protocol", ["web", "S", "D"])
async def test_empty_legacy_schema_change_is_real_completed_structure_without_provider_or_item(legacy, protocol):
    await fixtures.clear_files(legacy.flow)
    legacy.commits.clear()
    result = await call(legacy, "rename", protocol)
    assert result["status_code"] == 200
    async with legacy.flow.context.sessions() as session:
        job = (await session.exec(select(KnowledgeProcessingJob))).one()
        assert job.state == "succeeded" and job.total_count == 0 and not job.pending_dispatch and job.finished_at
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 1
    assert len(legacy.commits) == 1
    legacy.retired.assert_not_awaited()


async def test_space_without_writer_refuses_instead_of_using_unledgered_mutation(legacy):
    async with legacy.flow.context.sessions() as session:
        service = KnowledgeMetadataService(
            KnowledgeRepositoryImpl(session), KnowledgeFileRepositoryImpl(session), KnowledgePermissionService()
        )
        with pytest.raises(KnowledgeProcessingConflictError):
            await service.add_metadata_fields(
                legacy.flow.context.user, AddKnowledgeMetadataFieldsReq(**command("add", "web")[2])
            )
        await session.rollback()


@pytest.mark.parametrize("protocol", ["web", "S", "D"])
async def test_real_job_insert_failure_rolls_back_schema_instead_of_committing_legacy_update(legacy, protocol):
    engine = legacy.flow.context.engine.sync_engine
    rejected = []

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.lower().startswith("insert into knowledge_processing_job"):
            rejected.append(statement)
            raise RuntimeError("native ledger insert failed")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="native ledger insert failed"):
            await call(legacy, "add", protocol)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert len(rejected) == 1 and not legacy.commits
    async with legacy.flow.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        assert (await session.get(Knowledge, 40)).metadata_fields == [
            {"field_name": "note", "field_type": "string", "updated_at": 10}
        ]
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


@pytest.mark.parametrize("protocol", ["S", "D"])
async def test_original_openapi_write_scope_cannot_be_replaced_by_audit_web_payload(legacy, protocol):
    result = await call(legacy, "add", protocol, scope="knowledge:read")
    assert result["status_code"] == PermissionDeniedError.Code
    async with legacy.flow.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


async def test_qa_original_metadata_update_and_background_contract_are_preserved(legacy):
    async with legacy.flow.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.type = 1
        await session.commit()
    async with legacy.flow.context.sessions() as session:
        service = KnowledgeMetadataService(
            KnowledgeRepositoryImpl(session), KnowledgeFileRepositoryImpl(session), KnowledgePermissionService()
        )
        tasks = BackgroundTasks()
        result = await service.update_metadata_fields(
            legacy.flow.context.user, UpdateKnowledgeMetadataFieldsReq(**command("rename", "web")[2]), tasks
        )
        assert result.metadata_fields[0]["field_name"] == "alias" and len(tasks.tasks) == 1
        assert result.metadata_schema_revision == 0
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


@pytest.mark.parametrize("protocol", ["web", "S", "D"])
@pytest.mark.parametrize("operation", ["add", "rename", "delete"])
@pytest.mark.parametrize("missing_schema", [False, True])
async def test_empty_original_lists_are_authorized_noops_with_zero_writes_and_no_fake_job(
    legacy, protocol, operation, missing_schema
):
    async with legacy.flow.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        if missing_schema:
            root.metadata_fields = None
            await session.commit()
        before = root.model_dump(mode="json")
    legacy.commits.clear()
    writes = []
    engine = legacy.flow.context.engine.sync_engine

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await call(legacy, operation, protocol, empty=True)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["status_code"] == 200 and not writes and not legacy.commits
    if protocol == "web":
        assert result["data"]["metadata_fields"] == before["metadata_fields"]
        assert "processing_job" not in result["data"]
    else:
        assert result["data"] is True
    async with legacy.flow.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).model_dump(mode="json") == before
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()
    legacy.retired.assert_not_awaited()


@pytest.mark.parametrize("operation", ["add", "rename", "delete"])
async def test_empty_legacy_lists_recheck_original_container_edit_before_returning_schema(legacy, owner, operation):
    owner.auth.side_effect = PermissionDeniedError()
    result = await call(legacy, operation, empty=True)
    assert result["status_code"] == PermissionDeniedError.Code
    assert not legacy.commits
    async with legacy.flow.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
