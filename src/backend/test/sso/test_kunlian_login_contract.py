"""T039 覆盖 AC-01, AC-02, AC-03, AC-04, AC-13, AC-20, AC-22, AC-26。"""

import hashlib
import hmac
import json
from datetime import UTC
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianDirectoryNotReadyError,
    KunlianSessionExpiredError,
    KunlianSyncConflictError,
    KunlianTrustRejectedError,
)
from bisheng.common.errcode.user import UserNoWebMenuForLoginError
from bisheng.sso_sync.domain.clients.kunlian import KunlianTokenIdentity
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianIdentityBinding, KunlianWebSession
from bisheng.sso_sync.domain.services.kunlian_login import KunlianInternalTrust
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from test.sso import test_kunlian_projection as projection_tests
from test.sso.test_kunlian_admission import config
from test.user import test_kunlian_external_identity as user_tests

owner = user_tests.owner
directory_store = projection_tests.directory_store
projection = projection_tests.projection
PATH = "/api/v1/internal/kunlian/login"
SECRET = "fixture-independent-internal-secret"


@pytest.fixture
async def login(projection):
    create_projector, repository, user_owner, users, controls, _, key, _ = projection
    from bisheng.core.config.settings import decrypt_token, encrypt_token

    repository.encrypt_value, repository.decrypt_value = encrypt_token, decrypt_token
    repository.key_version = "fixture-token-key-v1"
    projector = create_projector()
    uid = await projector.project_identity(key)
    async with users() as session:
        session.add(UserRole(user_id=uid, role_id=910))
        await session.commit()
    async with controls() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        state.enabled = True
        session.add(state)
        await session.commit()
    module = import_module("bisheng.sso_sync.domain.services.kunlian_login")
    if not hasattr(module, "KunlianLoginService"):
        pytest.fail("T040 trusted login coordinator is not implemented", pytrace=False)
    clock = repository.clock
    now = int(clock().replace(tzinfo=UTC).timestamp())
    idp = SimpleNamespace(
        verify_id_token=AsyncMock(
            return_value=KunlianTokenIdentity(
                "https://fixture.example",
                "fixture-client",
                "subject-1",
                "external-a",
                "fixture-workspace",
                "fixture-sid",
                now - 60,
                now + 300,
            )
        ),
        introspect=AsyncMock(return_value=SimpleNamespace(expires_at=now + 300)),
    )
    requested = SimpleNamespace(request_directory_sync=AsyncMock(return_value=1))
    user_owner.require_login_access = AsyncMock()
    signed = []

    class Signer:
        def create_access_token(self, subject, **kwargs):
            signed.append((subject, kwargs))
            return (
                "fixture-local-jwt-"
                + hashlib.sha256(json.dumps([subject, kwargs], sort_keys=True).encode()).hexdigest()
            )

    nonces = set()

    async def reserve(nonce, ttl):
        if nonce in nonces:
            return False
        nonces.add(nonce)
        return True

    from pydantic import SecretStr

    trust = KunlianInternalTrust(
        key_id="fixture-key", secret=SecretStr(SECRET), reserve_nonce=reserve, clock=lambda: now
    )
    cfg = config()
    service = module.KunlianLoginService(
        repository,
        cfg,
        trust=trust,
        idp_client=idp,
        directory=requested,
        user_owner=user_owner,
        tenant_owner=projector.tenant_owner,
        signer_factory=Signer,
        multi_tenant_enabled=True,
        clock=clock,
    )
    body = {
        "connection_id": "fixture",
        "handoff_id": "fixture-handoff",
        "expected_nonce": "fixture-nonce",
        "browser_binding_hash": "b" * 64,
        "access_token": "fixture-private-AT",
        "id_token": "fixture-private-IDT",
        "expires_in": 300,
    }
    counter = 0

    async def call(*, data=None, source_allowed=True, raw=None):
        nonlocal counter
        counter += 1
        content = raw if raw is not None else json.dumps(body if data is None else data, separators=(",", ":")).encode()
        nonce = f"fixture-nonce-{counter:020d}"
        message = "\n".join(
            ("v1", "POST", PATH, "fixture-key", str(now), nonce, hashlib.sha256(content).hexdigest())
        ).encode()
        headers = {
            "X-Kunlian-Key-Id": "fixture-key",
            "X-Kunlian-Timestamp": str(now),
            "X-Kunlian-Nonce": nonce,
            "X-Kunlian-Signature": hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest(),
        }
        return await service.login(content, method="POST", path=PATH, headers=headers, source_allowed=source_allowed)

    return call, service, repository, user_owner, idp, requested, users, controls, signed, body, uid, key


async def test_verified_handoff_uses_current_user_and_fixed_sql_receipt(login):
    call, _, _, _, idp, requested, users, controls, signed, _, uid, _ = login
    first = await call()
    second = await call()
    assert first.local_jwt == second.local_jwt and first.expires_at == second.expires_at
    assert first.session_reference == second.session_reference and first.user_id == uid and first.tenant_id == 7
    assert idp.introspect.await_count == 2 and idp.verify_id_token.await_count == 2
    requested.request_directory_sync.assert_not_awaited()
    assert signed[0] == signed[1]
    assert set(signed[0][0]) == {"user_id", "user_name", "tenant_id", "token_version", "auth_source", "kunlian_session"}
    assert not any(value in repr(first) for value in ("fixture-private-AT", "fixture-private-IDT"))
    async with controls() as session:
        assert len((await session.exec(select(KunlianWebSession))).all()) == 1
    async with users() as session:
        assert len((await session.exec(select(User))).all()) == 1
        assert len((await session.exec(select(UserRole))).all()) == 1


async def test_directory_missing_refuses_and_only_requests_controlled_sync(login):
    call, _, _, _, _, requested, _, controls, signed, _, _, key = login
    async with controls() as session:
        row = await session.get(KunlianIdentityBinding, key)
        row.projected_revision = None
        row.projection_status = "PENDING"
        session.add(row)
        await session.commit()
    with pytest.raises(KunlianDirectoryNotReadyError):
        await call()
    assert requested.request_directory_sync.await_count == 1 and not signed
    async with controls() as session:
        assert not (await session.exec(select(KunlianWebSession))).all()


async def test_no_menu_or_revoked_replay_cannot_mint_another_session(login):
    call, _, repository, user_owner, _, _, _, controls, signed, _, _, _ = login
    user_owner.require_login_access.side_effect = UserNoWebMenuForLoginError()
    with pytest.raises(UserNoWebMenuForLoginError):
        await call()
    assert not signed
    user_owner.require_login_access.side_effect = None
    issued = await call()
    await repository.revoke_session(issued.session_reference, "LOGOUT")
    with pytest.raises(KunlianSessionExpiredError):
        await call()
    async with controls() as session:
        assert len((await session.exec(select(KunlianWebSession))).all()) == 1


@pytest.mark.parametrize("bad", ["source", "unknown_field", "different_body"])
async def test_untrusted_input_and_handoff_body_conflicts_reject(login, bad):
    call, _, _, _, idp, _, _, _, signed, body, _, _ = login
    if bad == "source":
        with pytest.raises(KunlianTrustRejectedError):
            await call(source_allowed=False)
        idp.verify_id_token.assert_not_awaited()
    elif bad == "unknown_field":
        from bisheng.common.errcode.sso_sync import KunlianLoginInvalidError

        with pytest.raises(KunlianLoginInvalidError):
            await call(data={**body, "user_id": 1})
        assert not signed
    else:
        await call()
        with pytest.raises(KunlianSyncConflictError):
            await call(raw=json.dumps(body, indent=2).encode())


async def test_control_policy_upgrade_fences_running_sync_and_old_sessions(directory_store):
    repository, sessions, _, _ = directory_store
    from test.sso.test_kunlian_directory import publish

    await repository.bind_tenant("fixture", "external-a", verified_local_tenant_id=7, expected_revision=None)
    await publish(repository)
    lease = await repository.claim_or_renew_lease("fixture", "old-worker", key_version="fixture", page_size=20)
    if not hasattr(repository, "apply_connection_policy"):
        pytest.fail("T040 explicit connection policy revision is not implemented", pytrace=False)
    async with sessions() as session:
        before = (await session.exec(select(KunlianIdentityBinding))).one().auth_epoch
    await repository.apply_connection_policy("fixture", enabled=True, policy_revision=2)
    with pytest.raises(KunlianSyncConflictError):
        await repository.stage_page(lease, tenants=[], members=[], next_cursor_ciphertext=None)
    with pytest.raises(KunlianSyncConflictError):
        await repository.apply_connection_policy("fixture", enabled=False, policy_revision=1)
    async with sessions() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        assert state.policy_revision == 2 and state.enabled is True
        assert (await session.exec(select(KunlianIdentityBinding))).one().auth_epoch > before


async def test_login_total_timeout_does_not_mint_a_session(login):
    import asyncio

    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    call, service, _, _, idp, _, _, controls, signed, _, _, _ = login
    service.timeout_seconds = 0.01

    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    idp.verify_id_token.side_effect = blocked
    with pytest.raises(KunlianDependencyUnavailableError):
        await call()
    assert not signed
    async with controls() as session:
        assert not (await session.exec(select(KunlianWebSession))).all()


async def test_registered_disable_then_enable_never_revives_old_cookie(login):
    call, service, repository, _, _, _, _, _, _, _, _, _ = login
    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    issued = await call()
    await repository.apply_connection_policy("fixture", enabled=False, policy_revision=2)
    with pytest.raises(KunlianDependencyUnavailableError):
        await call()
    await repository.apply_connection_policy("fixture", enabled=True, policy_revision=3)
    with pytest.raises(KunlianDependencyUnavailableError):
        await call()
    service.config.policy_revision = 3
    with pytest.raises(KunlianSessionExpiredError):
        await repository.load_admission_facts(issued.session_reference)
