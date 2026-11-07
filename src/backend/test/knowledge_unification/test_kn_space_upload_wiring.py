"""Original SPACE entry point, native chain and request-independent application DI."""

import asyncio
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge_space import SpaceFileSizeLimitError
from bisheng.core.context import tenant as context
from bisheng.knowledge.api import dependencies
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.permission.application import access
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from test.knowledge_unification import test_kn_upload as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload


async def test_actual_di_supplies_fresh_upload_app_without_borrowing_request_session(monkeypatch):
    monkeypatch.setattr(access, "get_f048_runtime", AsyncMock(return_value=object()))
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session:
            versions = await dependencies.get_knowledge_document_version_repository(session)
            documents = await dependencies.get_knowledge_document_repository(session)
            files = await dependencies.get_knowledge_file_repository(session)
            user = UserPayload(user_id=7, tenant_id=101, user_role=[])
            service = await dependencies.get_knowledge_space_service(
                Request({"type": "http", "headers": []}), session, user, versions, documents, files
            )
            first, second = service.upload_application_factory(), service.upload_application_factory()
            assert first is not second and first.repository is not second.repository
            assert first.user is user and first.sessions is dependencies.get_async_db_session
            assert first.admit == service._require_action
            assert first.make_record == service._new_file_permission_record
            assert first.actor_provider == service._permission_actor
            assert service.version_repo is versions and service.doc_repo is documents
            assert service.knowledge_file_repo is files
            assert not session.in_transaction()
    finally:
        await engine.dispose()


async def test_actual_size_over_role_limit_rejected_before_chain_and_permanent_blob(upload, monkeypatch):
    before = await chain_snapshot(upload)
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1))
    upload.legacy.storage.reset_mock()
    with pytest.raises(SpaceFileSizeLimitError):
        await upload.service.add_file(40, ["opaque-document"])
    upload.legacy.storage.put_object_sync.assert_not_called()
    upload.publish.assert_not_called()
    assert await chain_snapshot(upload) == before


async def chain_snapshot(upload):
    async with upload.context.sessions() as session:
        return {
            model.__tablename__: tuple(
                dict(row) for row in (await session.execute(sa.select(model.__table__).order_by(model.id))).mappings()
            )
            for model in (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion)
        }


async def test_tenant_limit_applies_to_admin_without_a_role_limit_before_registration(upload, monkeypatch):
    before = await chain_snapshot(upload)
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=1))
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_used_bytes", AsyncMock(return_value=0))
    with pytest.raises(BaseErrorCode):
        await upload.service.add_file(40, ["opaque-document"])
    assert await chain_snapshot(upload) == before
    upload.legacy.storage.put_object_sync.assert_not_called()
    upload.publish.assert_not_called()


@pytest.mark.parametrize("cancel", [False, True])
async def test_later_preparation_failure_compensates_only_this_prefix_before_dispatch(upload, monkeypatch, cancel):
    before = await chain_snapshot(upload)
    globals_ = upload.legacy.cls.prepare_one_file.__func__.__globals__
    download = globals_["file_download"]
    failure = asyncio.CancelledError() if cancel else OSError("second staging failed")

    def fail_second(path):
        if path == "second":
            raise failure
        return download(path)

    monkeypatch.setitem(globals_, "file_download", fail_second)
    removed = []

    def remove_after_sql_ack(**kwargs):
        file_id = int(kwargs["object_name"].split("/")[-1].split(".")[0])
        with upload.context.sync.connect() as connection:
            assert connection.execute(sa.select(KnowledgeFile.id).where(KnowledgeFile.id == file_id)).first() is None
        assert upload.projection._permission.rollback_created.await_count == 1
        removed.append(file_id)

    upload.legacy.storage.remove_object_sync.side_effect = remove_after_sql_ack
    with pytest.raises(type(failure)) as caught:
        await upload.service.add_file(40, ["opaque-document", "second"])
    assert caught.value is failure and len(removed) == 1
    assert await chain_snapshot(upload) == before
    upload.publish.assert_not_called()
    upload.service._initialize_child_resource_permissions.assert_not_awaited()


@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_registration_commit_never_dispatches_or_deletes_by_guess(upload, monkeypatch, committed):
    before = await chain_snapshot(upload)
    original = AsyncSession.commit
    failure = OSError("commit result unknown")

    async def fail_commit(session):
        if committed:
            await original(session)
        raise failure

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    with pytest.raises(OSError) as caught:
        await upload.service.add_file(40, ["opaque-document"])
    assert caught.value is failure
    progress = failure.space_upload_progress
    assert len(progress) == 1 and progress[0]["commit_outcome"] == "unknown" and not progress[0]["acknowledged"]
    after = await chain_snapshot(upload)
    for table, rows in before.items():
        assert len(after[table]) == len(rows) + int(committed)
        assert tuple(row for row in after[table] if row["id"] in {old["id"] for old in rows}) == rows
    upload.publish.assert_not_called()
    upload.legacy.storage.put_object_sync.assert_not_called()
    upload.legacy.storage.remove_object_sync.assert_not_called()
    upload.projection._permission.authorize_created.assert_not_awaited()
    upload.projection._permission.rollback_created.assert_not_awaited()


async def test_trusted_super_selected_tenant_covers_real_dispatch_and_restores_home(upload):
    user = upload.context.user
    user.tenant_id, user.is_global_super = 1, True
    user._runtime_credential_reference = {**user._runtime_credential_reference, "tenant_id": 1}
    actor = PermissionActor(user_id=7, tenant_id=1, super_admin=True)
    actor_token = set_current_permission_actor(actor)
    raw = context.set_current_tenant_id(1)
    original_visible = context.get_visible_tenant_ids()
    captured = []

    def dispatch(**kwargs):
        assert user.tenant_id == actor.current_tenant_id == 1
        assert context.current_tenant_id.get() == context.get_current_tenant_id() == 101
        assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()
        captured.append(kwargs)

    upload.publish.side_effect = dispatch
    try:
        with context.management_tenant_scope(101):
            result = await upload.service.add_file(40, ["opaque-document"])
            assert context.current_tenant_id.get() == 1 and context.get_current_tenant_id() == 101
        assert len(captured) == 1 and result[0].tenant_id == 101
        assert context.current_tenant_id.get() == 1 and context.get_visible_tenant_ids() == original_visible
        assert user.tenant_id == actor.current_tenant_id == 1
    finally:
        context.current_tenant_id.reset(raw)
        reset_current_permission_actor(actor_token)


async def test_scoped_failure_restores_original_management_pin_and_raw_home(upload):
    user = upload.context.user
    user.tenant_id, user.is_global_super = 1, True
    actor_token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=1, super_admin=True))
    raw = context.set_current_tenant_id(1)
    try:
        with context.management_tenant_scope(101):
            with pytest.raises(KeyError):
                await upload.service.add_file(40, ["missing-input"])
            assert context.current_tenant_id.get() == 1 and context.get_current_tenant_id() == 101
            assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()
        upload.publish.assert_not_called()
    finally:
        context.current_tenant_id.reset(raw)
        reset_current_permission_actor(actor_token)
