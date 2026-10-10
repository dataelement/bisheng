from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import (
    OpenApiDelegationHeaderRequiredError,
    OpenApiDelegationNotAllowedError,
    OpenApiDelegationTargetInvalidError,
    OpenApiEndUserInvalidError,
    OpenApiIdentityHeaderConflictError,
    OpenApiPrivilegedTargetError,
    OpenApiRemovedIdentityInputError,
)
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.services.identity_service import (
    assert_no_removed_identity_headers,
    parse_identity_headers,
    resolve_request_identity,
)


def principal(*, scopes=frozenset(), actor_kind="service_account"):
    return OpenApiPrincipal(
        credential_id=8,
        actor_kind=actor_kind,
        actor_id=3,
        actor_name="caller",
        tenant_id=4,
        resource_owner_user_id=6 if actor_kind == "service_account" else None,
        scopes=scopes,
        authorization_subject_type="service_account" if actor_kind == "service_account" else "user",
        authorization_subject_id=3,
        effective_user_id=None if actor_kind == "service_account" else 3,
    )


def test_new_headers_have_strict_syntax_and_conflict_rules():
    assert parse_identity_headers(on_behalf_of="12", end_user=None) == (12, None)
    assert parse_identity_headers(on_behalf_of=None, end_user="customer-7") == (None, "customer-7")
    with pytest.raises(OpenApiIdentityHeaderConflictError):
        parse_identity_headers(on_behalf_of="12", end_user="customer-7")
    for value in ("", "0", "-1", "+2", " 2", "user-2", "\uff11\uff12"):
        with pytest.raises(OpenApiDelegationTargetInvalidError):
            parse_identity_headers(on_behalf_of=value, end_user=None)
    for value in ("", "a" * 129, "line\nbreak", "用户"):
        with pytest.raises(OpenApiEndUserInvalidError):
            parse_identity_headers(on_behalf_of=None, end_user=value)


def test_removed_branded_identity_headers_are_not_aliases():
    with pytest.raises(OpenApiRemovedIdentityInputError):
        assert_no_removed_identity_headers([("X-Bisheng-On-Behalf-Of", "2")])
    assert_no_removed_identity_headers([("X-On-Behalf-Of", "2"), ("X-End-User", "external")])


async def test_delegate_missing_header_and_pat_delegation_fail_first(monkeypatch):
    with pytest.raises(OpenApiDelegationHeaderRequiredError):
        await resolve_request_identity(
            principal(scopes=frozenset({"delegate"})),
            on_behalf_of=None,
            end_user=None,
        )

    async def must_not_resolve(_target):
        raise AssertionError("target lookup must not run for PAT delegation")

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.OwnerRepository.get_active_natural_person",
        must_not_resolve,
    )
    with pytest.raises(OpenApiDelegationNotAllowedError):
        await resolve_request_identity(
            principal(scopes=frozenset({"delegate"}), actor_kind="natural_person"),
            on_behalf_of="9",
            end_user=None,
        )


async def test_delegation_checks_target_privilege_then_scope(monkeypatch):
    async def missing(_target):
        return None

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.OwnerRepository.get_active_natural_person",
        missing,
    )
    with pytest.raises(OpenApiDelegationTargetInvalidError):
        await resolve_request_identity(
            principal(scopes=frozenset({"delegate"})),
            on_behalf_of="9",
            end_user=None,
        )

    async def target(_target):
        return SimpleNamespace(user_id=9, tenant_id=4)

    async def privileged(_user, _tenant):
        return True

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.OwnerRepository.get_active_natural_person",
        target,
    )
    monkeypatch.setattr("bisheng.open_api.domain.services.identity_service._is_privileged_target", privileged)
    with pytest.raises(OpenApiPrivilegedTargetError):
        await resolve_request_identity(
            principal(scopes=frozenset({"delegate"})),
            on_behalf_of="9",
            end_user=None,
        )

    async def ordinary(_user, _tenant):
        return False

    async def denied(_credential, _user):
        return False

    monkeypatch.setattr("bisheng.open_api.domain.services.identity_service._is_privileged_target", ordinary)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.DelegateScopeService.target_allowed",
        denied,
    )
    with pytest.raises(OpenApiDelegationNotAllowedError):
        await resolve_request_identity(
            principal(scopes=frozenset({"delegate"})),
            on_behalf_of="9",
            end_user=None,
        )


async def test_successful_delegation_replaces_every_authorization_identity(monkeypatch):
    async def target(_target):
        return SimpleNamespace(user_id=9, tenant_id=4)

    async def ordinary(_user, _tenant):
        return False

    async def allowed(_credential, _user):
        return True

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.OwnerRepository.get_active_natural_person",
        target,
    )
    monkeypatch.setattr("bisheng.open_api.domain.services.identity_service._is_privileged_target", ordinary)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.DelegateScopeService.target_allowed",
        allowed,
    )
    resolved = await resolve_request_identity(
        principal(scopes=frozenset({"delegate"})),
        on_behalf_of="9",
        end_user=None,
    )
    assert resolved.mode == "D"
    assert (resolved.authorization_subject_type, resolved.authorization_subject_id) == ("user", 9)
    assert resolved.effective_user_id == resolved.resource_owner_user_id == 9
    assert resolved.on_behalf_of_user_id == 9
