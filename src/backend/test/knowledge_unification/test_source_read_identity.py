"""T350: keep request identity, credential narrowing and source tenant separate."""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.identity import PermissionActor
from bisheng.public_endpoints.domain.context import PublicApiPrincipal
from bisheng.resource_reference.application import read_identity as module
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity


@pytest.fixture
def request_identity(monkeypatch):
    user = UserPayload(user_id=7, user_name="holder", tenant_id=1, user_role=[], is_global_super=True)
    actor = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    resolve = AsyncMock(return_value=actor)
    monkeypatch.setattr(module, "resolve_permission_actor", resolve)
    monkeypatch.setattr(module, "_resolve_tenant_id", lambda: 101)
    monkeypatch.setattr(module, "is_tenant_filter_bypassed", lambda: False)
    monkeypatch.setattr(module, "get_visible_tenant_ids", lambda: frozenset({101, 1}))
    monkeypatch.setattr(module, "is_management_all_tenants", lambda: False)
    monkeypatch.setattr(module, "get_current_open_api_principal", lambda: None)
    monkeypatch.setattr(module, "get_current_public_api_principal", lambda: None)
    return user, resolve


async def test_jwt_home_never_replaces_trusted_request_pin(request_identity):
    user, resolve = request_identity
    facts = await AuthenticatedSourceReadIdentity().acapture(user)
    assert facts.request_tenant_id == 101
    assert user.tenant_id == 1
    resolve.assert_awaited_once_with(user)
    assert facts == await AuthenticatedSourceReadIdentity().acapture(user)


async def test_narrowing_and_subject_kind_change_the_fingerprint(request_identity):
    user, resolve = request_identity
    port = AuthenticatedSourceReadIdentity()
    original = await port.acapture(user)
    resolve.return_value = PermissionActor(
        user_id=7, current_tenant_id=101, super_admin=True, data_scope="personal_only"
    )
    narrowed = await port.acapture(user)
    resolve.return_value = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=101)
    service = await port.acapture(user)
    assert len({original.fingerprint, narrowed.fingerprint, service.fingerprint}) == 3


def _principal(**changes):
    principal = OpenApiPrincipal(
        credential_id=9,
        actor_kind="natural_person",
        actor_id=7,
        actor_name="holder",
        tenant_id=101,
        resource_owner_user_id=7,
        scopes=frozenset({"assistant:invoke"}),
        authorization_subject_type="user",
        authorization_subject_id=7,
        effective_user_id=7,
    )
    return principal.model_copy(update=changes)


@pytest.mark.parametrize("changes", [{"credential_id": 10}, {"scopes": frozenset({"assistant:read"})}, {"mode": "D"}])
async def test_credential_identity_and_issued_scope_are_bound(request_identity, monkeypatch, changes):
    user, _ = request_identity
    port = AuthenticatedSourceReadIdentity()
    monkeypatch.setattr(module, "get_current_open_api_principal", lambda: _principal())
    first = await port.acapture(user)
    monkeypatch.setattr(module, "get_current_open_api_principal", lambda: _principal(**changes))
    assert first.fingerprint != (await port.acapture(user)).fingerprint


async def test_web_session_reference_mutation_is_detected_without_exposing_it(request_identity):
    user, _ = request_identity
    user._runtime_credential_reference = {"kind": "web_session", "token_version": 2}
    port = AuthenticatedSourceReadIdentity()
    first = await port.acapture(user)
    user._runtime_credential_reference["token_version"] = 3
    assert first.fingerprint != (await port.acapture(user)).fingerprint
    assert "token_version" not in repr(first)


async def test_public_resource_identity_is_not_generic_guest_access(request_identity, monkeypatch):
    user, _ = request_identity
    port = AuthenticatedSourceReadIdentity()
    principal = PublicApiPrincipal(
        tenant_id=101, operator_user_id=7, operator_name="holder", resource_type="assistant", resource_id="a"
    )
    monkeypatch.setattr(module, "get_current_public_api_principal", lambda: principal)
    first = await port.acapture(user)
    monkeypatch.setattr(
        module, "get_current_public_api_principal", lambda: principal.model_copy(update={"resource_id": "b"})
    )
    assert first.fingerprint != (await port.acapture(user)).fingerprint


@pytest.mark.parametrize("bad", [True, None, -1])
async def test_missing_or_invalid_request_tenant_fails_closed(request_identity, monkeypatch, bad):
    user, _ = request_identity
    monkeypatch.setattr(module, "_resolve_tenant_id", lambda: bad)
    with pytest.raises(ResourceReferenceInvalidError):
        await AuthenticatedSourceReadIdentity().acapture(user)


async def test_bypass_and_bare_user_id_are_not_authenticated_identity(request_identity, monkeypatch):
    user, _ = request_identity
    with pytest.raises(ResourceReferenceInvalidError):
        await AuthenticatedSourceReadIdentity().acapture(user.user_id)
    monkeypatch.setattr(module, "is_tenant_filter_bypassed", lambda: True)
    with pytest.raises(ResourceReferenceInvalidError):
        await AuthenticatedSourceReadIdentity().acapture(user)
