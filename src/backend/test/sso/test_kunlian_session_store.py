"""T017 覆盖 AC-02, AC-07, AC-09, AC-10, AC-13, AC-18, AC-21, AC-26。"""

from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianSessionExpiredError,
    KunlianSyncConflictError,
    KunlianTrustRejectedError,
)
from bisheng.core.config.settings import decrypt_token, encrypt_token
from bisheng.sso_sync.domain.models.kunlian import (
    KunlianConnectionState,
    KunlianHandoffReceipt,
    KunlianIdentityBinding,
    KunlianTenantBinding,
    KunlianWebSession,
)
from test.sso import test_kunlian_directory as directory_cases
from test.sso.test_kunlian_directory import member, publish

directory_store = directory_cases.directory_store


@pytest.fixture
async def session_store(directory_store):
    directory, sessions, clock, module = directory_store
    await directory.bind_tenant("fixture", "external-a", verified_local_tenant_id=2, expected_revision=None)
    await publish(directory, members=[member(), member("member-2", "subject-2")])
    async with sessions() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        state.enabled = True
        session.add(state)
        mapping = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        mapping.materialized = True
        session.add(mapping)
        bindings = (await session.exec(select(KunlianIdentityBinding).order_by(KunlianIdentityBinding.member_id))).all()
        for i, binding in enumerate(bindings):
            binding.local_user_id = 101 + i
            binding.projected_revision = binding.source_revision
            binding.projection_status = "SUCCEEDED"
            session.add(binding)
        await session.commit()
    store = module.KunlianDirectoryRepository(
        sessions, clock=clock, encrypt_value=encrypt_token, decrypt_value=decrypt_token, key_version="fixture-v1"
    )
    return store, sessions, clock, bindings


async def issue(store, clock, binding, handoff="handoff-1", *, allow_multi_login=True, request_digest="a" * 64):
    return await store.issue_or_replay_handoff(
        "fixture",
        handoff,
        request_digest,
        binding_id=binding.identity_key,
        expected_source_revision=binding.source_revision,
        expected_auth_epoch=binding.auth_epoch,
        browser_binding_hash="b" * 64,
        client_id="fixture-client",
        sid="fixture-sid",
        workspace_id="fixture-workspace",
        access_token=SecretStr("fixture-upstream-at"),
        id_token=SecretStr("fixture-upstream-id"),
        access_token_expires_at=clock() + timedelta(minutes=5),
        hard_expires_at=clock() + timedelta(hours=1),
        signing_context={"user_id": binding.local_user_id, "tenant_id": 2, "token_version": 1},
        allow_multi_login=allow_multi_login,
    )


async def test_handoff_replay_is_same_session_and_cannot_extend_expiry(session_store):
    store, sessions, clock, bindings = session_store
    original = await issue(store, clock, bindings[0])
    clock.advance(1)
    other_instance = type(store)(
        store.session_factory,
        clock=clock,
        encrypt_value=encrypt_token,
        decrypt_value=decrypt_token,
        key_version="fixture-v1",
    )
    repeated = await issue(other_instance, clock, bindings[0])
    assert repeated.reference.get_secret_value() == original.reference.get_secret_value()
    assert repeated.hard_expires_at == original.hard_expires_at
    assert repeated.signing_context == original.signing_context
    assert original.reference.get_secret_value() not in repr(original)
    with pytest.raises(KunlianSyncConflictError):
        await issue(store, clock, bindings[0], request_digest="c" * 64)
    async with sessions() as session:
        rows = (await session.exec(select(KunlianWebSession))).all()
        assert len(rows) == 1
        assert rows[0].access_token_ciphertext != "fixture-upstream-at"
        assert rows[0].id_token_ciphertext != "fixture-upstream-id"
        receipt = await session.get(KunlianHandoffReceipt, "handoff-1")
        assert receipt.session_ref_ciphertext != original.reference.get_secret_value()


async def test_single_login_revokes_only_same_binding_and_replay_cannot_revive(session_store):
    store, _, clock, bindings = session_store
    first = await issue(store, clock, bindings[0])
    other_user = await issue(store, clock, bindings[1], "handoff-other")
    current = await issue(store, clock, bindings[0], "handoff-new", allow_multi_login=False)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(first.reference)
    with pytest.raises(KunlianSessionExpiredError):
        await issue(store, clock, bindings[0])
    assert (await store.load_admission_facts(other_user.reference)).binding.local_user_id == 102
    assert (await store.load_admission_facts(current.reference)).binding.local_user_id == 101


async def test_epoch_mismatch_persists_revocation_after_recovery(session_store):
    store, sessions, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    await store.record_manual_override(bindings[0].identity_key, True, expected_revision=bindings[0].source_revision)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(issued.reference)
    await store.record_manual_override(bindings[0].identity_key, False, expected_revision=bindings[0].source_revision)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(issued.reference)
    async with sessions() as session:
        assert (await session.get(KunlianWebSession, issued.session_hash)).state == "REVOKED"


async def test_expired_at_only_allows_protocol_and_hard_expiry_closes_it(session_store):
    store, sessions, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    clock.advance(301)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(issued.reference)
    protocol = await store.load_admission_facts(issued.reference, protocol_only=True)
    assert protocol.session.state == "REAUTH_REQUIRED"
    assert protocol.id_token is None and protocol.access_token is None
    clock.advance(3600)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(issued.reference, protocol_only=True)
    async with sessions() as session:
        assert (await session.get(KunlianWebSession, issued.session_hash)).state == "EXPIRED"


async def test_logout_ticket_requires_revocation_and_browser_and_is_single_use(session_store):
    store, _, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    with pytest.raises(KunlianTrustRejectedError):
        await store.issue_logout_ticket(issued.reference, "b" * 64)
    await store.revoke_session(issued.reference, "LOGOUT")
    ticket = await store.issue_logout_ticket(issued.reference, "b" * 64)
    with pytest.raises(KunlianTrustRejectedError):
        await store.redeem_logout_ticket(ticket, "wrong-browser")
    material = await store.redeem_logout_ticket(ticket, "b" * 64)
    assert material.id_token.get_secret_value() == "fixture-upstream-id"
    with pytest.raises(KunlianTrustRejectedError):
        await store.redeem_logout_ticket(ticket, "b" * 64)
    with pytest.raises(KunlianSessionExpiredError):
        await store.load_admission_facts(issued.reference)


async def test_failed_crypto_after_session_flush_rolls_back_whole_handoff(session_store):
    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    store, sessions, clock, bindings = session_store
    calls = 0

    def fail_receipt(value):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("fixture encryption unavailable")
        return encrypt_token(value)

    store.encrypt_value = fail_receipt
    with pytest.raises(KunlianDependencyUnavailableError):
        await issue(store, clock, bindings[0])
    async with sessions() as session:
        assert not (await session.exec(select(KunlianWebSession))).all()
        assert not (await session.exec(select(KunlianHandoffReceipt))).all()


async def test_ticket_expiry_and_hard_expiry_cleanup(session_store):
    store, sessions, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    await store.revoke_session(issued.reference, "LOGOUT")
    ticket = await store.issue_logout_ticket(issued.reference, "b" * 64)
    clock.advance(61)
    with pytest.raises(KunlianTrustRejectedError):
        await store.redeem_logout_ticket(ticket, "b" * 64)
    clock.advance(3600)
    assert await store.expire_sessions("fixture") == 1
    async with sessions() as session:
        expired = await session.get(KunlianWebSession, issued.session_hash)
        assert expired.state == "EXPIRED"
        assert expired.access_token_ciphertext == expired.id_token_ciphertext == ""


async def test_untrusted_browser_binding_is_rejected_without_consuming_ticket(session_store):
    store, _, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    await store.revoke_session(issued.reference, "LOGOUT")
    ticket = await store.issue_logout_ticket(issued.reference, "b" * 64)
    with pytest.raises(KunlianTrustRejectedError):
        await store.redeem_logout_ticket(ticket, "无效绑定")
    assert (await store.redeem_logout_ticket(ticket, "b" * 64)).client_id == "fixture-client"


async def test_local_protocol_does_not_require_upstream_token_decryption(session_store):
    store, _, clock, bindings = session_store
    issued = await issue(store, clock, bindings[0])
    clock.advance(301)

    def unavailable(_):
        raise ValueError("fixture encryption key unavailable")

    store.decrypt_value = unavailable
    facts = await store.load_admission_facts(issued.reference, protocol_only=True)
    assert facts.session.session_hash == issued.session_hash
    assert facts.access_token is None and facts.id_token is None
