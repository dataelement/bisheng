"""Loaded facts use the existing sole authorization path. 覆盖 AC: AC-68, AC-79, AC-83, AC-87, AC-89."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.application import authorization as port
from bisheng.app_runtime.domain.services import app_authorization_service as service
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.identity import PermissionActor


@pytest.mark.parametrize(
    "operation,actions",
    [
        ("management_preview", ["edit"]),
        ("destroy", ["delete"]),
        ("release_submit", ["edit", "publish"]),
        ("approved_start", ["publish"]),
    ],
)
async def test_loaded_export_retains_original_identity_facts_and_actions(monkeypatch, operation, actions):
    identity = UserPayload(user_id=11, user_name="caller", tenant_id=101, user_role=[])
    root = SimpleNamespace(id="app", tenant_id=101, owner_user_id=22, state="stopped")
    monkeypatch.setattr(
        service.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_type="user", subject_id=11, tenant_id=101)),
    )
    loader = AsyncMock(side_effect=AssertionError("loaded authorization must not reload in another Session"))
    monkeypatch.setattr(service.AppAuthorizationService, "load_app", loader)
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "check_business_action", check)
    await port.authorize_loaded_app(identity, root, operation)
    assert [call.kwargs["action"] for call in check.await_args_list] == actions
    assert all(call.args[0] is identity and call.kwargs["resource_id"] == root.id for call in check.await_args_list)
    loader.assert_not_awaited()


async def test_loaded_export_preserves_permission_denial(monkeypatch):
    monkeypatch.setattr(
        service.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_type="user", subject_id=11, tenant_id=101)),
    )
    monkeypatch.setattr(service, "check_business_action", AsyncMock(return_value=False))
    with pytest.raises(PermissionDeniedError):
        await port.authorize_loaded_app(
            UserPayload(user_id=11, user_name="caller", tenant_id=101, user_role=[]),
            SimpleNamespace(id="app", tenant_id=101, owner_user_id=22, state="stopped"),
            "destroy",
        )
