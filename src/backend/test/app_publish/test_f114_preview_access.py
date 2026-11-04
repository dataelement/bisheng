"""F114 preview purpose, task and visitor bindings fail closed (AC-38/AC-50/AC-69)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.app_publish import AppPreviewForbiddenError


@pytest.fixture
def access(monkeypatch):
    from bisheng.app_publish.domain.services import preview_access_service as mod
    from bisheng.app_runtime.application import preview_operations

    monkeypatch.setattr(preview_operations, "verify_preview_execution", AsyncMock(return_value=True))
    monkeypatch.setattr(mod, "preview_credential_is_live", AsyncMock(return_value=True))
    app = SimpleNamespace(id="app", tenant_id=3, owner_user_id=81, state="draft")
    viewer = SimpleNamespace(user_id=42, tenant_id=3)
    monkeypatch.setattr(mod, "load_app", AsyncMock(return_value=app))
    monkeypatch.setattr(mod, "resolve_preview_person", AsyncMock(return_value=viewer))
    monkeypatch.setattr(mod, "authorize_app", AsyncMock())
    monkeypatch.setattr(mod, "pending_app_reviews", AsyncMock(return_value=[]))
    row = SimpleNamespace(
        session_id="session",
        tenant_id=3,
        app_id="app",
        version_id="version",
        viewer_user_id=42,
        purpose="management",
        approval_instance_id=None,
        approval_task_id=None,
        credential_id=7,
        operation_id="op",
        status="running",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    return mod, app, viewer, row


async def test_management_capability_ceiling_is_current_viewer(access):
    mod, _app, viewer, row = access
    context = await mod.validate_binding(row, viewer_user_id=42, credential_id=7)
    assert context.capability_user_id == 42 and context.viewer_user_id == 42
    mod.authorize_app.assert_awaited_once_with(viewer, "app", "management_preview")


async def test_approval_uses_frozen_version_current_task_and_owner_ceiling(access):
    mod, _app, _viewer, row = access
    row.purpose = "approval"
    row.approval_instance_id = 8
    row.approval_task_id = 9
    mod.pending_app_reviews.return_value = [
        SimpleNamespace(tenant_id=3, app_id="app", version_id="version", instance_id=8, task_id=9)
    ]
    context = await mod.validate_binding(row, viewer_user_id=42, credential_id=7)
    assert context.capability_user_id == 81 and context.version_id == "version"
    mod.authorize_app.assert_not_awaited()
    mod.pending_app_reviews.return_value = []
    with pytest.raises(AppPreviewForbiddenError):
        await mod.validate_binding(row, viewer_user_id=42, credential_id=7)


@pytest.mark.parametrize(
    "changes,args",
    [
        ({"status": "starting"}, {}),
        ({"expires_at": datetime.utcnow() - timedelta(seconds=1)}, {}),
        ({"purpose": None}, {}),
        ({"operation_id": None}, {}),
        ({}, {"viewer_user_id": 99}),
        ({}, {"credential_id": 8}),
    ],
)
async def test_invalid_or_mixed_preview_refused(access, changes, args):
    mod, _app, _viewer, row = access
    for key, value in changes.items():
        setattr(row, key, value)
    with pytest.raises(AppPreviewForbiddenError):
        await mod.validate_binding(row, **{"viewer_user_id": 42, "credential_id": 7, **args})


async def test_ambiguous_purpose_is_not_inferred(access):
    mod, _app, viewer, _row = access
    mod.pending_app_reviews.return_value = [
        SimpleNamespace(tenant_id=3, app_id="app", version_id="version", instance_id=8, task_id=9)
    ]
    with pytest.raises(AppPreviewForbiddenError):
        await mod.qualify("app", "version", actor=viewer, purpose=None)
    grant = await mod.qualify("app", "version", actor=viewer, purpose="approval")
    assert grant.purpose == "approval" and grant.approval_task_id == 9


async def test_running_row_does_not_revive_a_cancelled_operation_or_revoked_key(access, monkeypatch):
    mod, _app, _viewer, row = access
    from bisheng.app_runtime.application import preview_operations

    monkeypatch.setattr(preview_operations, "verify_preview_execution", AsyncMock(return_value=False))
    with pytest.raises(AppPreviewForbiddenError):
        await mod.validate_binding(row, viewer_user_id=42, credential_id=7)
    monkeypatch.setattr(preview_operations, "verify_preview_execution", AsyncMock(return_value=True))
    mod.preview_credential_is_live.return_value = False
    with pytest.raises(AppPreviewForbiddenError):
        await mod.validate_binding(row, viewer_user_id=42, credential_id=7)
