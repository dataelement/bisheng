"""The thin export keeps the original frozen credential context. 覆盖 AC: AC-68, AC-79, AC-83, AC-87, AC-89."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.application import runtime_authorization as port
from bisheng.app_runtime.domain.services import runtime_authorization_service as service
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.permission.application.identity import PermissionActor


def context():
    return {
        "schema": 1,
        "origin_kind": "user_request",
        "purpose": "release_submit",
        "actor": {"subject_type": "user", "subject_id": 11, "tenant_id": 202},
        "credential_ref": {
            "kind": "web_session",
            "user_id": 11,
            "tenant_id": 202,
            "token_version": 7,
            "expires_at": 9999999999,
        },
        "target": {"tenant_id": 101, "app_id": "app", "version_id": "version"},
        "required_actions": ["edit", "publish"],
        "resume_after_restore": False,
    }


@pytest.fixture
def restoring(monkeypatch):
    user = UserPayload(
        user_id=11, user_name="original", user_role=["7"], tenant_id=202, token_version=7, is_global_super=True
    )
    resolver = AsyncMock(return_value=user)
    monkeypatch.setattr(service, "resolve_web_runtime_identity", resolver)
    monkeypatch.setattr(
        service.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_type="user", subject_id=11, tenant_id=202, super_admin=True)),
    )
    token = set_current_tenant_id(303)
    try:
        yield user, resolver
    finally:
        current_tenant_id.reset(token)


async def test_original_web_identity_survives_whole_transaction_and_restores_context(restoring):
    original, resolver = restoring
    frozen = context()
    async with port.user_authorization_context(
        frozen, SimpleNamespace(id="app", tenant_id=101), version_id="version"
    ) as actual:
        assert actual is original and actual.tenant_id == 202 and actual.user_role == ["7"]
        assert get_current_tenant_id() == 101
        resolver.assert_awaited_once_with(frozen["credential_ref"])
    assert get_current_tenant_id() == 303


async def test_failure_inside_context_restores_origin_without_identity_rebuild(restoring):
    with pytest.raises(RuntimeError, match="write failed"):
        async with port.user_authorization_context(
            context(), SimpleNamespace(id="app", tenant_id=101), version_id="version"
        ) as actual:
            assert actual is restoring[0]
            raise RuntimeError("write failed")
    assert get_current_tenant_id() == 303


async def test_revoked_original_credential_never_yields_a_replacement_owner(restoring):
    restoring[1].side_effect = PermissionDeniedError(reason="credential_revoked")
    with pytest.raises(PermissionDeniedError):
        async with port.user_authorization_context(
            context(), SimpleNamespace(id="app", tenant_id=101), version_id="version"
        ):
            pytest.fail("invalid credential yielded an identity")
    assert get_current_tenant_id() == 303
