"""T035 覆盖 AC-07, AC-08, AC-09, AC-11, AC-13, AC-17, AC-18, AC-25, AC-26。"""

from datetime import UTC, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianIdentityUnavailableError,
    KunlianSessionExpiredError,
    KunlianTrustRejectedError,
)
from bisheng.core.config.sso_sync import KunlianConf
from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding, KunlianTenantBinding, KunlianWebSession
from bisheng.sso_sync.domain.schemas.kunlian import KunlianActionContext
from test.sso import test_kunlian_session_store as store_tests

session_store = store_tests.session_store
directory_store = store_tests.directory_store


def config():
    base = "https://fixture.example"
    return KunlianConf(
        directory_enabled=True,
        login_enabled=True,
        connection_id="fixture",
        issuer=base,
        client_id="fixture-client",
        allowed_tenant_id="external-a",
        public_origin=base,
        redirect_uri=base + "/callback",
        logout_redirect_uri=base + "/logout/callback",
        endpoint_allowlist=[base + "/oidc/jwks"],
        client_secret_reference="fixture-client-secret-ref",
        sync_key_reference="fixture-directory-key-ref",
        internal_key_id="fixture-internal-key",
        internal_secret_reference="fixture-internal-ref",
        trusted_gateway_networks=["192.0.2.0/24"],
        csrf_secret_reference="fixture-csrf-ref",
        encryption_secret_reference="fixture-encryption-ref",
        max_directory_age_seconds=60,
        allowed_workspace_ids=["fixture-workspace"],
        state_semantics_revision="fixture-policy",
    )


@pytest.mark.parametrize(
    "origin",
    ["https://fixture.example/", "https://@fixture.example", "https://FIXTURE.example", "https://fixture.example:443"],
)
def test_origin_registration_rejects_values_the_browser_cannot_send(origin):
    """AC-13, AC-25:就绪判定必须与协议装配和网关的 Origin 合同一致。"""
    conf = config()
    conf.public_origin = origin
    conf.redirect_uri = origin + "/callback"
    conf.logout_redirect_uri = origin + "/logout/callback"
    assert conf.readiness_reasons(multi_tenant_enabled=True)


@pytest.fixture
async def admission(session_store):
    repository, sessions, clock, bindings = session_store
    issued = await store_tests.issue(repository, clock, bindings[0])
    try:
        module = import_module("bisheng.sso_sync.domain.services.kunlian_session")
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.sso_sync.domain.services.kunlian_session":
            raise
        pytest.fail("T036 admission service is not implemented", pytrace=False)
    idp = SimpleNamespace(
        introspect=AsyncMock(
            return_value=SimpleNamespace(
                expires_at=int((clock() + timedelta(minutes=5)).replace(tzinfo=UTC).timestamp())
            )
        )
    )
    facts = SimpleNamespace(user_id=101, user_name="当前名称", token_version=1, role_ids=(910,))
    user_owner = SimpleNamespace(
        read_current_qualification=AsyncMock(return_value=facts),
        build_admitted_payload=AsyncMock(return_value=SimpleNamespace(user_id=101, tenant_id=2)),
    )
    tenant_owner = SimpleNamespace(read_current_tenant=AsyncMock(return_value=2))
    service = module.KunlianSessionService(
        repository,
        config(),
        idp_client=idp,
        user_owner=user_owner,
        tenant_owner=tenant_owner,
        multi_tenant_enabled=True,
        csrf_secret=SecretStr("fixture-independent-csrf-secret"),
        clock=clock,
    )
    return service, repository, sessions, clock, issued, bindings[0], idp, user_owner, tenant_owner


def action(n=1, transport="HTTP"):
    return KunlianActionContext(transport=transport, action="workflow.use", request_id=f"fixture-request-{n}")


async def test_each_new_http_or_ws_action_introspects_without_allow_cache(admission):
    service, _, _, _, issued, _, idp, user_owner, _ = admission
    for i, transport in enumerate(("HTTP", "WEBSOCKET", "WEBSOCKET")):
        principal = await service.admit_kunlian_session(issued.reference, action(i, transport))
        assert principal.user_id == 101 and principal.tenant_id == 2
    assert idp.introspect.await_count == 3
    assert user_owner.read_current_qualification.await_count == 3
    for call in idp.introspect.await_args_list:
        expected = call.kwargs["expected"]
        assert (expected.subject, expected.client_id, expected.sid, expected.workspace_id) == (
            "subject-1",
            "fixture-client",
            "fixture-sid",
            "fixture-workspace",
        )
    assert "fixture-upstream-at" not in repr(principal)


@pytest.mark.parametrize("failure", ["disabled", "unknown", "override", "pending", "mapping", "stale", "unconfigured"])
async def test_sql_and_policy_failures_reject_before_introspection(admission, failure):
    service, _, sessions, clock, issued, binding, idp, _, _ = admission
    if failure in {"stale", "unconfigured"}:
        if failure == "stale":
            clock.advance(61)
        else:
            service.config.max_directory_age_seconds = None
    else:
        async with sessions() as session:
            row = await session.get(KunlianIdentityBinding, binding.identity_key)
            if failure in {"disabled", "unknown"}:
                row.admission_status = "DISABLED" if failure == "disabled" else "UNKNOWN"
            elif failure == "override":
                row.local_override = True
            elif failure == "pending":
                row.projected_revision = None
            else:
                mapping = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
                mapping.enabled = False
                session.add(mapping)
            session.add(row)
            await session.commit()
    with pytest.raises(
        (
            KunlianSessionExpiredError,
            KunlianIdentityUnavailableError,
            KunlianDirectoryNotReadyError,
            KunlianDependencyUnavailableError,
        )
    ):
        await service.admit_kunlian_session(issued.reference, action())
    idp.introspect.assert_not_awaited()


@pytest.mark.parametrize("failure", ["inactive", "mismatch", "network", "user", "tenant", "version"])
async def test_live_failures_are_closed_and_terminal_states_never_reactivate(admission, failure):
    service, _, sessions, _, issued, _, idp, user_owner, tenant_owner = admission
    if failure == "inactive":
        idp.introspect.side_effect = KunlianSessionExpiredError()
    elif failure == "mismatch":
        idp.introspect.side_effect = KunlianIdentityUnavailableError()
    elif failure == "network":
        idp.introspect.side_effect = KunlianDependencyUnavailableError()
    elif failure == "user":
        user_owner.read_current_qualification.side_effect = KunlianIdentityUnavailableError()
    elif failure == "tenant":
        tenant_owner.read_current_tenant.side_effect = KunlianIdentityUnavailableError()
    else:
        user_owner.read_current_qualification.return_value.token_version = 2
    with pytest.raises(
        (KunlianSessionExpiredError, KunlianIdentityUnavailableError, KunlianDependencyUnavailableError)
    ):
        await service.admit_kunlian_session(issued.reference, action())
    async with sessions() as session:
        row = await session.get(KunlianWebSession, issued.session_hash)
        if failure == "network":
            assert row.state == "ACTIVE"
        else:
            assert row.state in ("REVOKED", "REAUTH_REQUIRED")
    if failure in {"inactive", "mismatch"}:
        idp.introspect.side_effect = None
        with pytest.raises(KunlianSessionExpiredError):
            await service.admit_kunlian_session(issued.reference, action(2))
        assert idp.introspect.await_count == 1


async def test_access_token_expiry_keeps_only_bound_local_protocol(admission):
    service, repository, _, clock, issued, _, idp, user_owner, _ = admission
    clock.advance(301)
    with pytest.raises(KunlianSessionExpiredError):
        await service.admit_kunlian_session(issued.reference, action())
    repository.decrypt_value = lambda _: (_ for _ in ()).throw(ValueError("external token unavailable"))
    csrf = await service.derive_csrf(issued.reference)
    assert len(csrf) == 64
    await service.verify_csrf(issued.reference, csrf, origin="https://fixture.example")
    for origin, token in (("https://attacker.example", csrf), ("https://fixture.example", "昆" * 64)):
        with pytest.raises(KunlianTrustRejectedError):
            await service.verify_csrf(issued.reference, token, origin=origin)
    idp.introspect.assert_not_awaited()
    user_owner.read_current_qualification.assert_not_awaited()
    clock.advance(3600)
    with pytest.raises(KunlianSessionExpiredError):
        await service.derive_csrf(issued.reference)


@pytest.mark.parametrize("dependency", ["sql_read", "sql_transition", "permission", "protocol_sql"])
async def test_required_dependency_failures_never_escape_as_raw_errors(admission, monkeypatch, dependency):
    from sqlalchemy.exc import OperationalError

    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    service, repository, _, _, issued, _, idp, user_owner, _ = admission
    private_error = OperationalError("fixture-private-SQL", None, RuntimeError("fixture-private-cause"))
    if dependency in ("sql_read", "protocol_sql"):
        monkeypatch.setattr(repository, "load_admission_facts", AsyncMock(side_effect=private_error))
    elif dependency == "sql_transition":
        idp.introspect.side_effect = KunlianSessionExpiredError()
        monkeypatch.setattr(repository, "mark_reauthentication_required", AsyncMock(side_effect=private_error))
    else:
        user_owner.build_admitted_payload.side_effect = PermissionServiceUnavailableError(
            exception=RuntimeError("fixture-private-cause")
        )
    with pytest.raises(KunlianDependencyUnavailableError) as caught:
        if dependency == "protocol_sql":
            await service.derive_csrf(issued.reference)
        else:
            await service.admit_kunlian_session(issued.reference, action())
    assert "fixture-private" not in str(caught.value)


async def test_stale_registered_policy_cannot_admit_with_otherwise_ready_facts(admission):
    service, _, _, _, issued, _, idp, _, _ = admission
    service.config.policy_revision = 2
    with pytest.raises(KunlianDependencyUnavailableError):
        await service.admit_kunlian_session(issued.reference, action())
    idp.introspect.assert_not_awaited()
