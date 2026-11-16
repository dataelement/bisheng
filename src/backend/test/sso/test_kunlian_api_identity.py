"""F133 T002: API identity resolution is read-only and needs no browser/token."""

from datetime import datetime, timedelta
from importlib import import_module, util
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.config.sso_sync import KunlianConf
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.user.application.external_identity import (
    CurrentExternalAccount,
    KunlianExternalIdentityApplication,
)

MODULE = "bisheng.sso_sync.application.kunlian_identity"


def application_type():
    assert util.find_spec(MODULE) is not None, "T002 read-only identity application is missing"
    return import_module(MODULE).KunlianIdentityApplication


@pytest.fixture
def ports():
    now = datetime(2026, 11, 16, 8)
    config = KunlianConf(
        directory_enabled=True,
        connection_id="trusted-connection",
        issuer="https://identity.example",
        max_directory_age_seconds=300,
    )
    facts = SimpleNamespace(
        connection=SimpleNamespace(enabled=True, policy_revision=1),
        binding=SimpleNamespace(
            connection_id=config.connection_id,
            issuer=config.issuer,
            external_tenant_id="external-a",
            subject="oidc-subject",
            member_id="different-directory-member-id",
            identity_key="trusted-identity-key",
            admission_status="ACTIVE",
            local_override=False,
            local_user_id=42,
            projection_status="SUCCEEDED",
            projected_revision="r1",
            source_revision="r1",
        ),
        mapping=SimpleNamespace(
            connection_id=config.connection_id,
            external_tenant_id="external-a",
            local_tenant_id=7,
            revision=2,
            enabled=True,
            materialized=True,
        ),
        published_batch=SimpleNamespace(status="PUBLISHED", completed_at=now - timedelta(seconds=30)),
    )
    repository = SimpleNamespace(load_login_facts=AsyncMock(return_value=facts), clock=lambda: now)
    user_repository = SimpleNamespace(
        read_current_qualification=AsyncMock(return_value=CurrentExternalAccount(42, "current-name", 9, (910,)))
    )
    users = KunlianExternalIdentityApplication(user_repository, global_super_checker=AsyncMock(return_value=False))
    users.require_login_access = AsyncMock()
    tenants = SimpleNamespace(read_current_tenant=AsyncMock(return_value=7))
    return SimpleNamespace(config=config, facts=facts, repository=repository, users=users, tenants=tenants)


def make_application(ports):
    return application_type()(
        ports.repository,
        ports.config,
        user_owner=ports.users,
        tenant_owner=ports.tenants,
        multi_tenant_enabled=True,
    )


async def test_resolves_oidc_subject_to_current_payload_without_session_or_provisioning(ports):
    app = make_application(ports)
    with tenant_execution_scope(99):
        result = await app.resolve("trusted-connection", "external-a", "oidc-subject")
        assert get_current_tenant_id() == 99
    assert (result.user_id, result.tenant_id, result.user_name, result.token_version) == (42, 7, "current-name", 9)
    assert result.user_role == [910]
    assert result.is_global_super is False
    ports.repository.load_login_facts.assert_awaited_once_with(
        "trusted-connection", issuer=ports.config.issuer, subject="oidc-subject", external_tenant_id="external-a"
    )
    ports.users.repository.read_current_qualification.assert_awaited_once_with(42, identity_key="trusted-identity-key")
    ports.users.require_login_access.assert_awaited_once()


@pytest.mark.parametrize(
    "target,field,value,error",
    [
        ("connection", "enabled", False, KunlianDependencyUnavailableError),
        ("connection", "policy_revision", 2, KunlianDependencyUnavailableError),
        ("binding", "admission_status", "DISABLED", KunlianIdentityUnavailableError),
        ("binding", "local_override", True, KunlianIdentityUnavailableError),
        ("mapping", "enabled", False, KunlianIdentityUnavailableError),
        ("mapping", "materialized", False, KunlianDirectoryNotReadyError),
        ("binding", "local_user_id", None, KunlianDirectoryNotReadyError),
        ("binding", "projection_status", "PENDING", KunlianDirectoryNotReadyError),
        ("binding", "projected_revision", "old", KunlianDirectoryNotReadyError),
        ("published_batch", "status", "FAILED", KunlianDirectoryNotReadyError),
        ("published_batch", "completed_at", None, KunlianDirectoryNotReadyError),
        ("published_batch", "completed_at", datetime(2026, 11, 16, 7, 54, 59), KunlianDirectoryNotReadyError),
        ("published_batch", "completed_at", datetime(2026, 11, 16, 8, 0, 1), KunlianDirectoryNotReadyError),
    ],
)
async def test_rejects_untrusted_or_incomplete_directory_before_user_lookup(ports, target, field, value, error):
    setattr(getattr(ports.facts, target), field, value)
    with tenant_execution_scope(99), pytest.raises(error):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")
    ports.users.repository.read_current_qualification.assert_not_awaited()


@pytest.mark.parametrize("missing", ["mapping", "published_batch"])
async def test_missing_directory_fact_does_not_auto_onboard(ports, missing):
    setattr(ports.facts, missing, None)
    with pytest.raises(KunlianDirectoryNotReadyError):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")


@pytest.mark.parametrize("error", [KunlianBindingConflictError, KunlianDirectoryNotReadyError])
async def test_unknown_or_conflicting_identity_is_not_replaced_by_default_user(ports, error):
    ports.repository.load_login_facts.side_effect = error()
    with pytest.raises(error):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")
    ports.users.repository.read_current_qualification.assert_not_awaited()


@pytest.mark.parametrize("owner", ["users", "tenants"])
async def test_current_disabled_user_or_inactive_tenant_membership_is_rejected(ports, owner):
    if owner == "users":
        ports.users.repository.read_current_qualification.side_effect = KunlianIdentityUnavailableError()
    else:
        ports.tenants.read_current_tenant.side_effect = KunlianIdentityUnavailableError()
    with tenant_execution_scope(99):
        with pytest.raises(KunlianIdentityUnavailableError):
            await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")
        assert get_current_tenant_id() == 99


async def test_refuses_global_super_even_with_valid_mapping(ports):
    ports.users.global_super_checker.return_value = True
    with pytest.raises(KunlianIdentityUnavailableError):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")


async def test_tenant_admin_payload_remains_real_user_not_global_admin(ports, monkeypatch):
    # Tenant admin is a current-tenant relation, not a global role to blacklist.
    ports.users.repository.read_current_qualification.return_value = CurrentExternalAccount(
        42, "tenant-admin", 10, (911,)
    )
    result = await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")
    assert (result.user_id, result.tenant_id, result.user_role, result.is_global_super) == (42, 7, [911], False)
    from bisheng.permission.application import relation_api
    from bisheng.permission.application.identity import resolve_permission_actor

    checker = AsyncMock(return_value=True)
    monkeypatch.setattr(relation_api, "is_tenant_admin", checker)
    actor = await resolve_permission_actor(result)
    assert actor.tenant_admin_tenant_ids == frozenset({7})
    assert actor.super_admin is False
    checker.assert_awaited_once_with(42, 7)


@pytest.mark.parametrize(
    "values",
    [
        ("wrong", "external-a", "oidc-subject"),
        ("trusted-connection", "", "oidc-subject"),
        ("trusted-connection", "external-a", " "),
        ("trusted-connection", "external-a", "s" * 129),
    ],
)
async def test_invalid_identity_never_reads_or_falls_back(ports, values):
    with pytest.raises(KunlianIdentityUnavailableError):
        await make_application(ports).resolve(*values)
    ports.repository.load_login_facts.assert_not_awaited()


@pytest.mark.parametrize(
    "target,field,value", [("binding", "subject", "other"), ("mapping", "external_tenant_id", "other")]
)
async def test_mismatched_read_port_facts_cannot_change_identity(ports, target, field, value):
    setattr(getattr(ports.facts, target), field, value)
    with pytest.raises(KunlianBindingConflictError):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")


async def test_default_factory_uses_runtime_read_ports_without_login_binding(ports, monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.sso_sync.application import runtime

    onboarding = SimpleNamespace(
        current_qualification=AsyncMock(return_value=CurrentExternalAccount(42, "onboarded", 11, (910,)))
    )
    services = SimpleNamespace(
        config=ports.config,
        projection=SimpleNamespace(repository=ports.repository, user_owner=ports.users, tenant_owner=ports.tenants),
        onboarding=onboarding,
    )
    provider = SimpleNamespace(worker_services=AsyncMock(return_value=services))
    app = SimpleNamespace(state=SimpleNamespace(kunlian_runtime_provider=provider))
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    service = await import_module(MODULE).get_kunlian_identity_application(app)
    result = await service.resolve("trusted-connection", "external-a", "oidc-subject")
    assert (result.user_name, result.token_version) == ("onboarded", 11)
    onboarding.current_qualification.assert_awaited_once_with(ports.facts.binding)
    assert runtime.get_runtime_provider(app) is provider


async def test_different_current_tenant_is_not_accepted(ports):
    ports.tenants.read_current_tenant.return_value = 8
    with pytest.raises(KunlianIdentityUnavailableError):
        await make_application(ports).resolve("trusted-connection", "external-a", "oidc-subject")
