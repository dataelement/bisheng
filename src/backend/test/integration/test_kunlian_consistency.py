"""T078:真实双连接池/Redis 竞争。未配置环境时待执行,不使用 SQLite。"""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from test.integration.kunlian_fixtures import live_storage as live_storage


async def test_lease_takeover_fences_old_publish_and_preserves_complete_directory(live_storage):
    """AC-05, AC-06, AC-16, AC-24, AC-26:旧执行者不能覆盖新完整批次。"""
    from bisheng.common.errcode.sso_sync import KunlianSyncConflictError
    from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, utc_now

    store = live_storage
    first, second = store.repositories
    await store.publish()
    previous = (await first.get_status(store.connection_id))["active_batch_id"]
    leases = await asyncio.gather(
        *(
            repo.claim_or_renew_lease(store.connection_id, name, key_version="test", page_size=20)
            for repo, name in ((first, "one"), (second, "two"))
        )
    )
    assert sum(lease is not None for lease in leases) == 1
    old = next(lease for lease in leases if lease is not None)
    await first.stage_page(old, tenants=[], members=[], next_cursor_ciphertext="test-cursor")
    assert (await second.get_status(store.connection_id))["active_batch_id"] == previous
    # 只调整本夹具随机连接的租约期限。接管和锁竞争仍由真实数据库执行。
    async with store.sessions[1]() as session, session.begin():
        state = await session.get(KunlianConnectionState, store.connection_id)
        state.lease_until = utc_now() - timedelta(seconds=1)
        session.add(state)
    current = await second.claim_or_renew_lease(store.connection_id, "takeover", key_version="test", page_size=20)
    assert current is not None and current.fence > old.fence
    with pytest.raises(KunlianSyncConflictError):
        await first.stage_page(old, tenants=[], members=[], next_cursor_ciphertext=None)
    with pytest.raises(KunlianSyncConflictError):
        await first.publish_directory(old, issuer=store.issuer)
    await second.stage_page(current, tenants=[], members=[], next_cursor_ciphertext=None)
    await second.publish_directory(current, issuer=store.issuer)
    status = await first.get_status(store.connection_id)
    assert status["active_batch_id"] == current.batch_id and status["member_count"] == 0
    failed = await first.claim_or_renew_lease(store.connection_id, "failure", key_version="test", page_size=20)
    await first.mark_failed(failed, "DIRECTORY_INVALID")
    status = await second.get_status(store.connection_id)
    assert status["active_batch_id"] == current.batch_id and status["directory_status"] == "FAILED"


async def test_owner_fence_serializes_manual_disable_against_late_profile(live_storage):
    """AC-03, AC-17, AC-18, AC-23, AC-26:Owner 持久栅栏保护人工停用与新资料。"""
    from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
    from bisheng.user.domain.models.user import User

    store = live_storage
    first, second = store.owners
    identity = store.identity()
    initial = await first.reserve(identity, "a" * 64)
    uid = await first.ensure_shadow(identity, "a" * 64, operation=initial)
    late_value = store.identity(name="迟到旧资料")
    late = await first.reserve(late_value, "b" * 64)
    manual = await second.reserve_manual_status(
        uid, identity_key=identity.identity_key, source_revision="c" * 64, disabled=True, source_active=True
    )
    results = await asyncio.gather(
        first.ensure_shadow(late_value, "b" * 64, operation=late),
        second.set_manual_status(
            uid, identity_key=identity.identity_key, disabled=True, source_active=True, operation=manual
        ),
        return_exceptions=True,
    )
    assert isinstance(results[0], KunlianBindingConflictError) and results[1] is None
    renamed = store.identity(name="新资料")
    newest = await first.reserve(renamed, "d" * 64)
    assert await first.ensure_shadow(renamed, "d" * 64, operation=newest) == uid
    async with store.sessions[1]() as session:
        user = await session.get(User, uid)
        assert (user.user_name, user.delete, user.disable_source) == ("新资料", 1, "manual")


async def test_handoff_uniqueness_revocation_restore_and_ciphertext_cleanup(live_storage):
    """AC-07, AC-09, AC-17, AC-18, AC-26:并发交接唯一,恢复不能复活旧会话。"""
    from pydantic import SecretStr
    from sqlmodel import select

    from bisheng.common.errcode.sso_sync import KunlianSessionExpiredError
    from bisheng.sso_sync.domain.models.kunlian import KunlianHandoffReceipt, KunlianWebSession, utc_now

    store = live_storage
    binding = await store.prepare_session()
    first, second = store.repositories

    async def issue(repo, handoff):
        return await repo.issue_or_replay_handoff(
            store.connection_id,
            handoff,
            "a" * 64,
            binding_id=binding.identity_key,
            expected_source_revision=binding.source_revision,
            expected_auth_epoch=binding.auth_epoch,
            browser_binding_hash="b" * 64,
            client_id="e2e-client",
            sid="e2e-sid",
            workspace_id="e2e-workspace",
            access_token=SecretStr("synthetic-storage-only-at"),
            id_token=SecretStr("synthetic-storage-only-id"),
            access_token_expires_at=utc_now() + timedelta(minutes=5),
            hard_expires_at=utc_now() + timedelta(hours=1),
            signing_context={"user_id": binding.local_user_id, "tenant_id": 1, "token_version": 1},
        )

    handoff = store.connection_id
    one, repeated = await asyncio.gather(issue(first, handoff), issue(second, handoff))
    assert one.session_hash == repeated.session_hash
    assert one.reference.get_secret_value() == repeated.reference.get_secret_value()
    async with store.sessions[1]() as session:
        receipts = (
            await session.exec(
                select(KunlianHandoffReceipt).where(
                    KunlianHandoffReceipt.connection_id == store.connection_id,
                )
            )
        ).all()
        assert len(receipts) == 1
    await second.record_manual_override(binding.identity_key, True, expected_revision=binding.source_revision)
    with pytest.raises(KunlianSessionExpiredError):
        await first.load_admission_facts(one.reference)
    await first.record_manual_override(binding.identity_key, False, expected_revision=binding.source_revision)
    with pytest.raises(KunlianSessionExpiredError):
        await second.load_admission_facts(one.reference)
    binding = await second.get_binding(binding.identity_key)
    # 人工状态改变后投影必须重新完成。本测试只建立仓储前提。
    async with first.projection_scope(binding.identity_key) as (_, _, complete):
        await complete(binding.local_user_id)
    new = await issue(second, "e2e-" + uuid4().hex)
    await first.revoke_session(new.reference, "LOGOUT")
    with pytest.raises(KunlianSessionExpiredError):
        await second.load_admission_facts(new.reference)
    async with store.sessions[0]() as session, session.begin():
        for session_hash in (one.session_hash, new.session_hash):
            row = await session.get(KunlianWebSession, session_hash)
            row.hard_expires_at = utc_now() - timedelta(seconds=1)
            session.add(row)
        for row in (
            await session.exec(
                select(KunlianHandoffReceipt).where(
                    KunlianHandoffReceipt.connection_id == store.connection_id,
                )
            )
        ).all():
            row.expires_at = utc_now() - timedelta(seconds=1)
            session.add(row)
    await second.expire_sessions(store.connection_id)
    await first.expire_handoff_material(store.connection_id)
    async with store.sessions[1]() as session:
        assert (await session.get(KunlianWebSession, new.session_hash)).access_token_ciphertext == ""
        assert (await session.get(KunlianHandoffReceipt, handoff)).session_ref_ciphertext == ""


async def test_redis_nonce_claim_is_single_winner_across_clients(live_storage):
    """AC-26:真实 Redis 上两个协议实例争用同一签名 nonce。"""
    import hashlib
    import hmac
    import time

    from pydantic import SecretStr

    from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
    from bisheng.sso_sync.domain.services.kunlian_login import KunlianInternalTrust, TrustedHandoff

    key_id, nonce, timestamp = live_storage.connection_id, uuid4().hex, str(int(time.time()))
    secret, path, body = b"synthetic-storage-signing-key", "/api/v1/internal/kunlian/login", b"{}"
    message = "\n".join(("v1", "POST", path, key_id, timestamp, nonce, hashlib.sha256(body).hexdigest()))
    headers = {
        "x-kunlian-key-id": key_id,
        "x-kunlian-timestamp": timestamp,
        "x-kunlian-nonce": nonce,
        "x-kunlian-signature": hmac.new(secret, message.encode(), hashlib.sha256).hexdigest(),
    }
    key = "kunlian:internal:nonce:" + hashlib.sha256((key_id + "\n" + nonce).encode()).hexdigest()
    first, second = live_storage.redis

    def protocol(client):
        async def reserve(key, ttl):
            return bool(await client.set(key, "1", nx=True, ex=ttl))

        return KunlianInternalTrust(key_id=key_id, secret=SecretStr(secret.decode()), reserve_nonce=reserve)

    try:
        results = await asyncio.gather(
            *(
                protocol(client).verify_internal_request("POST", path, body, headers, source_allowed=True)
                for client in (first, second)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, TrustedHandoff) for result in results) == 1
        assert sum(isinstance(result, KunlianTrustRejectedError) for result in results) == 1
        assert 0 < await second.ttl(key) <= 121
    finally:
        await first.delete(key)
