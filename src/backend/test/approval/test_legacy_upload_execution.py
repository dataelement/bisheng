"""Live legacy HTTP decisions retain applicant attribution and real executor authority."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.approval.api.endpoints import approval as api
from bisheng.approval.domain.models import approval_request as requests
from bisheng.approval.domain.models.approval_request import ApprovalRequest
from bisheng.approval.domain.services import approval_service as decisions
from bisheng.approval.domain.services.approval_service import ApprovalService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.models import space_channel_member as members
from bisheng.common.models.space_channel_member import SpaceChannelMember, UserRoleEnum
from bisheng.core import database
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as spaces
from bisheng.user.domain.models import user_role
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from bisheng.user.domain.repositories import runtime_identity
from bisheng.utils import http_middleware
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


@pytest.fixture
async def legacy_decision(upload, monkeypatch):
    from bisheng.approval.application import legacy_upload
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)

    context = upload.context
    monkeypatch.setattr(legacy_upload, "get_async_db_session", context.sessions)
    metadata = sa.MetaData()
    for model in (ApprovalRequest, SpaceChannelMember, User, Tenant, UserTenant, UserRole):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    c.name,
                    c.type.copy(),
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if c.name in {"create_time", "update_time", "password_update_time"}
                    else c.server_default,
                )
                for c in model.__table__.columns
            ],
        )
    async with context.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    for module in (database, decisions, requests, members, runtime_identity, user_role):
        monkeypatch.setattr(module, "get_async_db_session", context.sessions)
    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(ApprovalService, "_send_result_notify", AsyncMock())
    action = AsyncMock()
    monkeypatch.setattr(spaces.KnowledgeSpaceService, "_require_action", action)
    monkeypatch.setattr(spaces.KnowledgeSpaceService, "update_folder_update_time", AsyncMock())
    monkeypatch.setattr(spaces.KnowledgeSpaceService, "preview_cache_key_for_split_rule", lambda *args: "native-rule")
    async with context.sessions() as session:
        session.add_all(
            [
                User(user_id=7, user_name="Executor", password="not-a-credential", token_version=0),
                User(user_id=8, user_name="Applicant", password="not-a-credential", token_version=0),
                UserTenant(user_id=7, tenant_id=101, is_active=1, status="active"),
                UserTenant(user_id=8, tenant_id=101, is_active=1, status="active"),
                UserRole(id=91, user_id=7, role_id=4),
                UserRole(id=92, user_id=8, role_id=5),
                SpaceChannelMember(
                    id=97,
                    business_id="40",
                    business_type="space",
                    user_id=7,
                    user_role=UserRoleEnum.CREATOR,
                    is_active=True,
                ),
                ApprovalRequest(
                    id=31,
                    tenant_id=101,
                    space_id=40,
                    applicant_user_id=8,
                    applicant_user_name="Original Applicant",
                    file_count=1,
                    reviewer_user_ids=[7],
                    payload_json={
                        "files": [{"file_path": "opaque-document"}],
                        "space_id": 40,
                        "parent_folder_id": None,
                    },
                ),
            ]
        )
        await session.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: context.user
    return SimpleNamespace(upload=upload, app=app, action=action)


async def decide(value):
    async with AsyncClient(transport=ASGITransport(app=value.app), base_url="http://native") as client:
        return await client.post("/api/v1/approval/requests/31/decision", json={"action": "approve"})


async def test_live_legacy_decision_preserves_creator_and_quota_without_impersonating_executor(legacy_decision):
    value = legacy_decision
    response = await decide(value)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "finalized", response.json()["data"].get("safety_reason")
    async with value.upload.context.sessions() as session:
        row = await session.get(ApprovalRequest, 31)
        [created] = row.payload_json["finalized_file_ids"]
        actual = await session.get(KnowledgeFile, created)
        assert (actual.user_id, actual.user_name) == (8, "Original Applicant")
        assert actual.updater_id == 7
    quota = spaces.QuotaService.get_knowledge_space_upload_limit_bytes.await_args.args[0]
    assert quota.user_id == 8 and quota.user_role == [-999] and not quota.is_admin()
    assert spaces.SpaceFileDao.get_user_total_file_size.await_args.args == (8,)
    projected = value.upload.projection._permission.authorize_created.await_args.kwargs
    assert projected["actor"].subject_id == 7 and not projected["actor"].super_admin
    assert projected["owner_user_id"] == 8
    value.upload.publish.assert_called_once()


async def test_removed_reviewer_never_starts_legacy_upload(legacy_decision):
    value = legacy_decision
    async with value.upload.context.sessions() as session:
        row = await session.get(SpaceChannelMember, 97)
        row.status = "REJECTED"
        await session.commit()
    response = await decide(value)
    assert response.json()["status_code"] != 200
    value.upload.publish.assert_not_called()
    value.upload.legacy.storage.put_object_sync.assert_not_called()


def scope_snapshot():
    from bisheng.core.context import tenant as scope
    from bisheng.permission.application.identity import get_current_permission_actor

    return (
        scope.get_current_tenant_id(),
        scope.get_visible_tenant_ids(),
        scope.get_admin_scope_tenant_id(),
        scope.get_is_management_api(),
        scope.is_tenant_filter_bypassed(),
        get_current_permission_actor(),
    )


@pytest.mark.parametrize("change", ["reviewer", "applicant", "operator", "request", "foreign_row"])
async def test_late_admission_change_blocks_before_download_and_restores_http_scope(
    legacy_decision, monkeypatch, change
):
    from bisheng.approval.application import legacy_upload

    value = legacy_decision
    before = scope_snapshot()
    resolve = legacy_upload.resolve_preview_person
    count = 0

    async def current_person(ident):
        nonlocal count
        person = await resolve(ident)
        count += 1
        if count == 2:
            async with value.upload.context.sessions() as session:
                if change == "reviewer":
                    row = await session.get(SpaceChannelMember, 97)
                    row.status = "REJECTED"
                elif change == "applicant":
                    row = await session.get(User, 8)
                    row.delete = 1
                elif change == "operator":
                    row = await session.get(User, 7)
                    row.token_version += 1
                else:
                    row = await session.get(ApprovalRequest, 31)
                    if change == "foreign_row":
                        row.tenant_id = 202
                    else:
                        row.parent_folder_id = 999
                await session.commit()
        return person

    monkeypatch.setattr(legacy_upload, "resolve_preview_person", current_person)
    response = await decide(value)
    assert (response.json().get("data") or {}).get("status") != "finalized"
    assert scope_snapshot() == before
    value.upload.publish.assert_not_called()
    value.upload.legacy.storage.put_object_sync.assert_not_called()
    if change == "foreign_row":
        with value.upload.context.sync.connect() as connection:
            assert (
                connection.execute(sa.select(ApprovalRequest.status).where(ApprovalRequest.id == 31)).scalar_one()
                == "approved"
            )
    # No file was even registered while admission no longer held.
    async with value.upload.context.sessions() as session:
        from sqlmodel import select

        assert len((await session.exec(select(KnowledgeFile))).all()) == 2


async def test_foreign_approved_request_never_changes_http_tenant_or_starts_io(legacy_decision):
    value = legacy_decision
    async with value.upload.context.sessions() as session:
        row = await session.get(ApprovalRequest, 31)
        row.tenant_id = 202
        await session.commit()
    before = scope_snapshot()
    response = await decide(value)
    assert (response.json().get("data") or {}).get("status") != "finalized"
    assert scope_snapshot() == before
    value.upload.publish.assert_not_called()
    value.upload.legacy.storage.put_object_sync.assert_not_called()


async def test_success_restores_original_http_scope_and_completed_decision_is_not_reexecuted(legacy_decision):
    value = legacy_decision
    before = scope_snapshot()
    response = await decide(value)
    assert response.json()["data"]["status"] == "finalized"
    assert scope_snapshot() == before
    again = await decide(value)
    assert again.json()["status_code"] != 200
    value.upload.publish.assert_called_once()


async def test_actual_message_composition_executes_same_native_approved_upload(legacy_decision):
    from bisheng.message.api.dependencies import get_message_service
    from bisheng.message.domain.models.inbox_message import InboxMessage

    value = legacy_decision
    async with value.upload.context.sessions() as session:
        service = await get_message_service(session)
    handler = service._handler_map["request_department_knowledge_space_upload"]
    message = InboxMessage(
        content=[{"metadata": {"business_type": "approval_request_id", "data": {"approval_request_id": 31}}}]
    )
    await handler.on_approved(message, 7)
    async with value.upload.context.sessions() as session:
        assert (await session.get(ApprovalRequest, 31)).status == "finalized"
    value.upload.publish.assert_called_once()


@pytest.mark.parametrize("count", [1, 3])
async def test_payload_is_frozen_once_and_not_reread_for_each_blob(legacy_decision, count):
    value = legacy_decision
    async with value.upload.context.sessions() as session:
        row = await session.get(ApprovalRequest, 31)
        row.file_count = count
        row.payload_json = {**row.payload_json, "files": [{"file_path": "opaque-document"}] * count}
        await session.commit()
    statements = []

    def query(_connection, _cursor, statement, _parameters, _context, _many):
        if "approval_request" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sa.event.listen(value.upload.context.engine.sync_engine, "before_cursor_execute", query)
    try:
        response = await decide(value)
    finally:
        sa.event.remove(value.upload.context.engine.sync_engine, "before_cursor_execute", query)
    assert response.json()["data"]["status"] == "finalized"
    full = [sql for sql in statements if "approval_request.payload_json" in sql]
    # Original decision has three DAO full reads including final response;
    # this executor has exactly two: initial freeze and final locked comparison.
    assert len(full) == 5
    assert len(statements) > len(full)


async def test_download_tail_revocation_blocks_registration_before_blob_or_dispatch(legacy_decision, monkeypatch):
    value = legacy_decision
    globals_ = value.upload.legacy.cls.prepare_one_file.__func__.__globals__
    download = globals_["file_download"]

    def revoked(path):
        result = download(path)
        with value.upload.context.sync.begin() as connection:
            connection.execute(
                sa.update(SpaceChannelMember).where(SpaceChannelMember.id == 97).values(status="REJECTED")
            )
        return result

    monkeypatch.setitem(globals_, "file_download", revoked)
    response = await decide(value)
    assert response.json()["data"]["status"] == "finalize_failed"
    value.upload.legacy.storage.put_object_sync.assert_not_called()
    value.upload.publish.assert_not_called()


async def test_final_locked_read_rejects_changed_frozen_payload(legacy_decision, monkeypatch):
    from bisheng.approval.domain.repositories.legacy_upload_execution_repository import LegacyUploadExecutionRepository

    value = legacy_decision
    finalize = LegacyUploadExecutionRepository.afinalize

    async def changed(self, session, evidence, ids):
        # Direct SQL deliberately keeps the scalar revision unchanged. The final
        # complete comparison must still reject a substituted original command.
        async with value.upload.context.sessions() as other:
            row = await other.get(ApprovalRequest, 31)
            row.payload_json = {**row.payload_json, "files": [{"file_path": "substituted"}]}
            await other.commit()
        return await finalize(self, session, evidence, ids)

    monkeypatch.setattr(LegacyUploadExecutionRepository, "afinalize", changed)
    response = await decide(value)
    assert response.json()["data"]["status"] == "finalize_failed"
    async with value.upload.context.sessions() as session:
        assert "finalized_file_ids" not in (await session.get(ApprovalRequest, 31)).payload_json


async def test_actual_permission_denial_is_not_replaced_by_reviewer_role(legacy_decision):
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError

    value = legacy_decision
    value.action.side_effect = SpacePermissionDeniedError()
    response = await decide(value)
    assert response.json()["data"]["status"] == "finalize_failed"
    value.upload.legacy.storage.put_object_sync.assert_not_called()
    value.upload.publish.assert_not_called()


async def test_cancel_restores_original_scope_without_false_finalization(legacy_decision, monkeypatch):
    import asyncio

    value = legacy_decision
    globals_ = value.upload.legacy.cls.prepare_one_file.__func__.__globals__

    def cancel(_path):
        raise asyncio.CancelledError()

    monkeypatch.setitem(globals_, "file_download", cancel)
    before = scope_snapshot()
    with pytest.raises(asyncio.CancelledError):
        await decide(value)
    assert scope_snapshot() == before
    async with value.upload.context.sessions() as session:
        assert (await session.get(ApprovalRequest, 31)).status == "approved"
    value.upload.publish.assert_not_called()


async def test_dispatch_unknown_is_reported_failed_without_erasing_registered_files(legacy_decision):
    value = legacy_decision
    value.upload.publish.side_effect = OSError("broker acknowledgement unknown")
    response = await decide(value)
    assert response.json()["data"]["status"] == "finalize_failed"
    async with value.upload.context.sessions() as session:
        from sqlmodel import select

        assert len((await session.exec(select(KnowledgeFile))).all()) == 3
    value.upload.projection._permission.rollback_created.assert_not_awaited()
