"""T612: delayed knowledge work restores the original credential and narrowing."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import OpenApiDelegationNotAllowedError, OpenApiScopeMissingError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.application import processing_identity as identity
from bisheng.open_api.application import knowledge_processing_identity as api_identity
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import (
    PermissionActor,
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)


@contextmanager
def request_context(actor, principal=None, tenant=101):
    tenant_token = set_current_tenant_id(tenant)
    actor_token = set_current_permission_actor(actor)
    principal_token = set_current_open_api_principal(principal)
    try:
        yield
    finally:
        reset_current_open_api_principal(principal_token)
        reset_current_permission_actor(actor_token)
        current_tenant_id.reset(tenant_token)


def web_user():
    user = UserPayload(user_id=11, tenant_id=101, user_role=[], token_version=3)
    user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": 11,
        "tenant_id": 101,
        "token_version": 3,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat(),
    }
    return user


async def capture(user, entry_kind="web"):
    return await identity.capture_processing_actor(user, space_id=1, required_action="edit", entry_kind=entry_kind)


async def test_web_capture_keeps_only_verified_reference_and_frozen_action_scope():
    user = web_user()
    actor = PermissionActor(user_id=11, tenant_id=101)
    with request_context(actor):
        captured = await capture(user)
    assert captured.actor_user_id == 11 and captured.tenant_id == 101
    reference = captured.reference
    assert reference["space_id"] == 1 and reference["required_action"] == "edit"
    assert reference["credential_reference"] == user._runtime_credential_reference
    reference["credential_reference"]["user_id"] = 99
    assert captured.reference["credential_reference"]["user_id"] == 11
    assert not any(secret in captured.payload_json for secret in ["access_token", "bearer", "password"])


async def test_web_restore_uses_real_session_reference_and_restores_ambient_context(monkeypatch):
    user = web_user()
    actor = PermissionActor(user_id=11, tenant_id=101, data_scope=DATA_SCOPE_PERSONAL)
    with request_context(actor):
        captured = await capture(user)
    fresh = web_user()
    resolve = AsyncMock(return_value=fresh)
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", resolve)
    monkeypatch.setattr(
        identity,
        "resolve_permission_actor",
        AsyncMock(
            return_value=PermissionActor(
                user_id=11,
                tenant_id=101,
                super_admin=True,
                data_scope=DATA_SCOPE_ALL,
            )
        ),
    )
    outer = PermissionActor(user_id=77, tenant_id=202)
    with request_context(outer, tenant=202):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101) as restored:
            assert restored is fresh and get_current_tenant_id() == 101
            assert get_current_open_api_principal() is None
            actual = get_current_permission_actor()
            assert actual.user_id == 11 and not actual.super_admin and actual.data_scope == DATA_SCOPE_PERSONAL
        assert get_current_tenant_id() == 202 and get_current_permission_actor() is outer
    resolve.assert_awaited_once_with(user._runtime_credential_reference)


@pytest.mark.parametrize("change", [{"expires_at": "2000-01-01T00:00:00"}, {"user_id": 99}, {"access_token": "secret"}])
async def test_invalid_web_origin_cannot_be_captured(change):
    user = web_user()
    user._runtime_credential_reference.update(change)
    with request_context(PermissionActor(user_id=11, tenant_id=101)):
        with pytest.raises(PermissionDeniedError):
            await capture(user)


async def test_revoked_web_origin_never_falls_back_to_audit_user_id(monkeypatch):
    user = web_user()
    with request_context(PermissionActor(user_id=11, tenant_id=101)):
        captured = await capture(user)
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", AsyncMock(side_effect=PermissionDeniedError()))
    make_user = AsyncMock()
    monkeypatch.setattr(UserPayload, "init_login_user", make_user)
    with pytest.raises(PermissionDeniedError):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101):
            pytest.fail("revoked web credential was restored")
    make_user.assert_not_awaited()


@pytest.mark.parametrize("change", [{"tenant_id": 202}, {"actor_user_id": 0}, {"schema_version": 2}])
async def test_restore_rejects_wrong_tenant_or_malformed_persisted_origin(change):
    with request_context(PermissionActor(user_id=11, tenant_id=101)):
        reference = (await capture(web_user())).reference
    reference.update(change)
    with pytest.raises(PermissionDeniedError):
        async with identity.restore_processing_actor(reference, tenant_id=101):
            pytest.fail("invalid origin was restored")


def principal(kind="service_account", *, delegated=False, scopes=None):
    user = kind == "natural_person"
    return OpenApiPrincipal(
        credential_id=20,
        actor_kind=kind,
        actor_id=11 if user else 7,
        actor_name="Original",
        tenant_id=101,
        resource_owner_user_id=11,
        scopes=frozenset(scopes or {"knowledge:write"}),
        mode="D" if delegated else "S",
        authorization_subject_type="user" if user or delegated else "service_account",
        authorization_subject_id=11 if user or delegated else 7,
        effective_user_id=11 if user or delegated else None,
        on_behalf_of_user_id=11 if delegated else None,
    )


@pytest.fixture
def api_ports(monkeypatch):
    from bisheng.open_api.domain.services import access_context, identity_service

    current = [principal()]
    row = SimpleNamespace(
        id=20, tenant_id=101, subject_kind="service_account", subject_id=7, is_valid_at=lambda now: True
    )
    get = AsyncMock(return_value=row)
    monkeypatch.setattr(api_identity.CredentialRepository, "get", get)
    monkeypatch.setitem(
        api_identity.SUBJECT_RESOLVERS, "service_account", AsyncMock(side_effect=lambda row: current[0])
    )
    monkeypatch.setitem(api_identity.SUBJECT_RESOLVERS, "natural_person", AsyncMock(side_effect=lambda row: current[0]))
    monkeypatch.setattr(api_identity, "revalidate_service_account", AsyncMock(side_effect=lambda value: value))
    monkeypatch.setattr(
        identity_service.OwnerRepository,
        "get_active_natural_person",
        AsyncMock(return_value=SimpleNamespace(tenant_id=101)),
    )
    allowed = AsyncMock(return_value=True)
    monkeypatch.setattr(identity_service.DelegateScopeService, "target_allowed", allowed)
    monkeypatch.setattr(identity_service, "_is_privileged_target", AsyncMock(return_value=False))
    monkeypatch.setattr(access_context.settings.open_api, "pat_enabled", True)
    monkeypatch.setattr(
        access_context.TenantSettingService,
        "get_policy",
        AsyncMock(return_value=SimpleNamespace(enabled=True, data_scope=DATA_SCOPE_ALL)),
    )
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    return SimpleNamespace(current=current, row=row, get=get, delegation_allowed=allowed)


@pytest.mark.parametrize("kind", ["service_account", "natural_person"])
async def test_api_restore_reenters_real_access_context_and_intersects_scope_and_actor(api_ports, kind):
    original = principal(kind)
    actor = PermissionActor(
        subject_type=original.authorization_subject_type,
        subject_id=original.authorization_subject_id,
        tenant_id=101,
        data_scope=DATA_SCOPE_PERSONAL,
    )
    api_ports.row.subject_kind, api_ports.row.subject_id = kind, original.actor_id
    with request_context(actor, original):
        captured = await capture(web_user(), "open_api")
    api_ports.current[0] = principal(kind, scopes={"knowledge:write", "model:invoke"})
    with request_context(None, tenant=202):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101) as restored:
            assert get_current_open_api_principal() is restored
            assert restored.credential_id == 20 and restored.has_scope("knowledge:write")
            assert not restored.has_scope("model:invoke")
            actual = get_current_permission_actor()
            assert actual.subject_type == original.authorization_subject_type
            assert actual.subject_id == original.authorization_subject_id
            assert actual.data_scope == actor.data_scope
        assert get_current_tenant_id() == 202 and get_current_open_api_principal() is None


async def test_delegated_restore_revalidates_same_target_and_current_delegate_policy(api_ports):
    original = principal(delegated=True, scopes={"knowledge:write", "delegate"})
    with request_context(PermissionActor(user_id=11, tenant_id=101), original):
        captured = await capture(web_user(), "open_api")
    api_ports.current[0] = principal(scopes={"knowledge:write", "delegate"})
    async with identity.restore_processing_actor(captured.reference, tenant_id=101) as restored:
        assert restored.mode == "D" and restored.on_behalf_of_user_id == 11
        assert get_current_permission_actor().fga_subject == "user:11"
    api_ports.delegation_allowed.assert_awaited_once_with(20, 11)
    api_ports.delegation_allowed.return_value = False
    with pytest.raises(OpenApiDelegationNotAllowedError):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101):
            pytest.fail("revoked delegation was restored")


@pytest.mark.parametrize("invalid", ["revoked", "tenant", "scope", "subject"])
async def test_api_recovery_refuses_revoked_changed_or_narrowed_credential(api_ports, invalid):
    original = principal()
    with request_context(PermissionActor(subject_type="service_account", subject_id=7, tenant_id=101), original):
        captured = await capture(web_user(), "open_api")
    if invalid == "revoked":
        api_ports.row.is_valid_at = lambda now: False
    elif invalid == "tenant":
        api_ports.row.tenant_id = 202
    elif invalid == "subject":
        api_ports.current[0] = principal().model_copy(update={"actor_id": 8, "authorization_subject_id": 8})
    else:
        api_ports.current[0] = principal(scopes={"knowledge:read"})
    with pytest.raises((PermissionDeniedError, OpenApiScopeMissingError)):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101):
            pytest.fail("invalid API credential was restored")


async def test_api_capture_does_not_save_a_bearer_or_accept_an_unrelated_actor(api_ports):
    original = principal()
    actor = PermissionActor(user_id=99, tenant_id=101)
    with request_context(actor, original):
        with pytest.raises(PermissionDeniedError):
            await capture(web_user(), "open_api")
    with request_context(PermissionActor(subject_type="service_account", subject_id=7, tenant_id=101), original):
        captured = await capture(web_user(), "open_api")
    reference = deepcopy(captured.reference)
    assert reference["credential_reference"]["credential_id"] == 20
    assert not any(secret in captured.payload_json for secret in ["access_token", "bearer", "password"])


async def test_api_restore_cannot_replace_original_audit_owner(api_ports):
    original = principal()
    with request_context(PermissionActor(subject_type="service_account", subject_id=7, tenant_id=101), original):
        reference = (await capture(web_user(), "open_api")).reference
    reference["actor_user_id"] = 99
    with pytest.raises(PermissionDeniedError):
        async with identity.restore_processing_actor(reference, tenant_id=101):
            pytest.fail("changed original owner was restored")
