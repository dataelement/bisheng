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
    context = upload.context
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
    for module in (database, requests, members, runtime_identity, user_role):
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
    assert response.json()["data"]["status"] == "finalized"
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
