"""``CredentialService`` unit tests (F049 T009, pairs with T010).

Test-First: written before ``open_api/domain/services/credential_service.py``.
Everything runs against the in-process aiosqlite database + Redis (real or
fakeredis) provided by ``test/open_api/conftest.py``; no middleware needed.

覆盖 AC: AC-02 (plaintext once / hash only), AC-03 (revoke deletes the cache
entry), AC-05 (validity predicate + lazy expiry), AC-06 (no default scopes /
unknown scope rejected), AC-08 (edit effective immediately), AC-09 (batch
revoke), AC-10 (last-used write coalescing), AC-11 (soft revoke keeps history),
AC-12 (five audit events, never a plaintext).
"""

from __future__ import annotations

import hashlib
import json
import string
from datetime import datetime, timedelta

import pytest
from sqlmodel import col, select

from bisheng.common.errcode.open_api import (
    ApiCredentialNotFoundError,
    OpenApiDelegateScopeNotEnabledError,
    OpenApiExtensionScopeNotDeployedError,
    OpenApiUnknownScopeError,
)
from bisheng.common.services.config_service import settings
from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.domain.models.api_credential import (
    KEY_MASK_FILL,
    KEY_PREFIX,
    KEY_SECRET_LENGTH,
    REVOKE_REASON_BATCH,
    REVOKE_REASON_EXPIRED,
    REVOKE_REASON_MANUAL,
    SUBJECT_KIND_HOSTED_APP,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    SUBJECT_KIND_SHARE_LINK,
    ApiCredential,
    ApiCredentialDao,
)
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest, KeyUpdateRequest
from bisheng.open_api.domain.services.credential_service import (
    CREDENTIAL_CACHE_KEY,
    LAST_USED_THROTTLE_KEY,
    CredentialService,
)

# The subject id every test issues against; a real service-account row is only
# needed once the validator resolves subjects (T011), not here.
SUBJECT_ID = "77001"
_URLSAFE_ALPHABET = set(string.ascii_letters + string.digits + "-_")


async def _issue(operator, **kwargs):
    request = KeyIssueRequest(
        name=kwargs.pop("name", "key-1"),
        scopes=kwargs.pop("scopes", []),
        expires_at=kwargs.pop("expires_at", None),
    )
    return await CredentialService.issue(
        operator,
        kwargs.pop("subject_kind", SUBJECT_KIND_SERVICE_ACCOUNT),
        kwargs.pop("subject_id", SUBJECT_ID),
        request,
    )


async def _row(oapi_db, credential_id: int) -> ApiCredential:
    async with oapi_db() as session:
        row = await ApiCredentialDao.aget(session, credential_id)
    assert row is not None
    return row


async def _audit_rows(oapi_db) -> list[AuditLog]:
    async with oapi_db() as session:
        result = await session.exec(select(AuditLog).order_by(col(AuditLog.action)))
        return list(result.all())


# ---------------------------------------------------------------------------
# issue
# ---------------------------------------------------------------------------


async def test_issue_returns_plaintext_once_and_stores_hash_only(oapi_db, tenant_admin_payload):
    """AC-02: the plaintext exists only in the issue response; the row holds sha256 + mask parts."""
    issued = await _issue(tenant_admin_payload, name="ci-key")

    plaintext = issued.plaintext
    secret = plaintext.removeprefix(KEY_PREFIX)
    assert plaintext.startswith(KEY_PREFIX)
    assert len(secret) == KEY_SECRET_LENGTH == 43
    assert set(secret) <= _URLSAFE_ALPHABET
    assert issued.key_mask == f"{KEY_PREFIX}{KEY_MASK_FILL}{plaintext[-4:]}"

    row = await _row(oapi_db, issued.id)
    assert row.token_hash == hashlib.sha256(plaintext.encode()).hexdigest()
    assert row.key_prefix == KEY_PREFIX and row.last4 == plaintext[-4:]
    assert row.created_by == tenant_admin_payload.user_id
    assert row.tenant_id == tenant_admin_payload.tenant_id
    assert row.revoked_at is None and row.revoke_reason is None and row.last_used_at is None
    # Nothing on the persisted row (nor the masked view) can reconstruct the key.
    assert plaintext not in json.dumps(row.model_dump(mode="json"))
    listed = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID)
    assert [item.id for item in listed] == [issued.id]
    assert plaintext not in json.dumps([item.model_dump(mode="json") for item in listed])

    # Two issues never collide and never reuse the secret.
    other = await _issue(tenant_admin_payload, name="ci-key-2")
    assert other.plaintext != plaintext


async def test_default_scopes_empty_and_unknown_scope_rejected_26025(oapi_db, tenant_admin_payload):
    """AC-06: nothing is granted unless asked for; a code outside the registry is refused."""
    issued = await _issue(tenant_admin_payload)
    assert issued.scopes == []
    assert (await _row(oapi_db, issued.id)).scopes == []

    with pytest.raises(OpenApiUnknownScopeError) as excinfo:
        await _issue(tenant_admin_payload, scopes=["knowledge:read", "knowledge:destroy"])
    assert excinfo.value.code == 26025

    granted = await _issue(tenant_admin_payload, scopes=["knowledge:read", "knowledge:read", "workflow:invoke"])
    assert granted.scopes == ["knowledge:read", "workflow:invoke"]  # de-duplicated, order kept


async def test_issue_rejects_delegate_and_gated_toolkit_scopes(oapi_db, tenant_admin_payload, monkeypatch):
    """AC-14 / AC-13 at the service boundary: ``delegate`` is 26024, toolkit scopes need the switch."""
    with pytest.raises(OpenApiDelegateScopeNotEnabledError) as excinfo:
        await _issue(tenant_admin_payload, scopes=["delegate"])
    assert excinfo.value.code == 26024  # specific, not the generic unknown-scope 26025

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    with pytest.raises(OpenApiExtensionScopeNotDeployedError) as excinfo:
        await _issue(tenant_admin_payload, scopes=["app:manage"])
    assert excinfo.value.code == 26023

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    issued = await _issue(tenant_admin_payload, scopes=["app:manage", "identity:read"])
    assert issued.scopes == ["app:manage", "identity:read"]


async def test_issue_hosted_app_kind_accepted(oapi_db, redis_client, tenant_admin_payload):
    """D2 "主体解析器" promise: F049 stores / revokes ``hosted_app`` credentials even without a resolver."""
    issued = await _issue(tenant_admin_payload, subject_kind=SUBJECT_KIND_HOSTED_APP, subject_id="app-9")
    row = await _row(oapi_db, issued.id)
    assert row.subject_kind == SUBJECT_KIND_HOSTED_APP and row.subject_id == "app-9"

    revoked = await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_HOSTED_APP, "app-9", issued.id)
    assert revoked.revoked_at is not None

    # ``share_link`` never owns a credential row — a programming error, not user input.
    with pytest.raises(ValueError):
        await _issue(tenant_admin_payload, subject_kind=SUBJECT_KIND_SHARE_LINK, subject_id="s1")


async def test_validity_predicate(oapi_db, redis_client, tenant_admin_payload):
    """AC-05: validity is a predicate over two timestamps; ``expires_at == now`` is already expired."""
    now = datetime.now()
    expiring = await _issue(tenant_admin_payload, name="exp", expires_at=now + timedelta(seconds=30))
    row = await _row(oapi_db, expiring.id)
    assert row.is_valid_at(now)
    assert not row.is_valid_at(now + timedelta(seconds=30))  # boundary
    assert not row.is_valid_at(now + timedelta(seconds=31))

    forever = await _row(oapi_db, (await _issue(tenant_admin_payload, name="forever")).id)
    assert forever.expires_at is None and forever.is_valid_at(now + timedelta(days=3650))

    await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, forever.id)
    assert not (await _row(oapi_db, forever.id)).is_valid_at(now)


# ---------------------------------------------------------------------------
# revoke / update — row shape + active cache invalidation
# ---------------------------------------------------------------------------


async def test_revoke_soft_keeps_row_and_history(oapi_db, redis_client, tenant_admin_payload):
    """AC-11: revoke is a soft flag — the row, its subject and its issuer survive for audit."""
    issued = await _issue(tenant_admin_payload, name="to-revoke", scopes=["knowledge:read"])
    before = await _row(oapi_db, issued.id)

    revoked = await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, issued.id)
    assert revoked.revoked_at is not None and revoked.revoke_reason == REVOKE_REASON_MANUAL

    row = await _row(oapi_db, issued.id)
    assert row is not None and row.revoke_reason == REVOKE_REASON_MANUAL
    assert row.subject_id == before.subject_id and row.created_by == before.created_by
    assert row.token_hash == before.token_hash and row.scopes == ["knowledge:read"]
    assert row.name == "to-revoke"

    # Revoking a key of another subject is 26026, never a silent no-op.
    other = await _issue(tenant_admin_payload, subject_id="99999", name="foreign")
    with pytest.raises(ApiCredentialNotFoundError) as excinfo:
        await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, other.id)
    assert excinfo.value.code == 26026


async def test_revoke_deletes_cache_key(oapi_db, redis_client, tenant_admin_payload):
    """AC-03: the positive cache is actively deleted on revoke — 5s must not depend on the TTL."""
    issued = await _issue(tenant_admin_payload, name="cached")
    token_hash = (await _row(oapi_db, issued.id)).token_hash
    cache_key = CREDENTIAL_CACHE_KEY.format(token_hash)
    await redis_client.aset(cache_key, {"credential_id": issued.id}, expiration=300)
    assert await redis_client.aget(cache_key) is not None

    await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, issued.id)
    assert await redis_client.aget(cache_key) is None


async def test_update_scopes_name_expires_invalidates_cache_immediately(oapi_db, redis_client, tenant_admin_payload):
    """AC-08: editing a key changes the existing key in place and drops its cache entry."""
    issued = await _issue(tenant_admin_payload, name="old", scopes=["knowledge:read"])
    row = await _row(oapi_db, issued.id)
    cache_key = CREDENTIAL_CACHE_KEY.format(row.token_hash)
    await redis_client.aset(cache_key, {"credential_id": issued.id}, expiration=300)

    expires = datetime.now() + timedelta(days=1)
    updated = await CredentialService.update(
        tenant_admin_payload,
        SUBJECT_KIND_SERVICE_ACCOUNT,
        SUBJECT_ID,
        issued.id,
        KeyUpdateRequest(name="new", scopes=["knowledge:write"], expires_at=expires),
    )
    assert updated.name == "new" and updated.scopes == ["knowledge:write"]
    assert await redis_client.aget(cache_key) is None

    after = await _row(oapi_db, issued.id)
    assert after.token_hash == row.token_hash  # same key, no rotation
    assert after.scopes == ["knowledge:write"] and after.name == "new"
    assert after.expires_at is not None

    # Absent fields keep their value; an explicit null clears the expiry.
    await CredentialService.update(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, issued.id, KeyUpdateRequest(name="newer")
    )
    kept = await _row(oapi_db, issued.id)
    assert kept.expires_at is not None and kept.scopes == ["knowledge:write"] and kept.name == "newer"

    await CredentialService.update(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, issued.id, KeyUpdateRequest(expires_at=None)
    )
    assert (await _row(oapi_db, issued.id)).expires_at is None

    with pytest.raises(OpenApiUnknownScopeError):
        await CredentialService.update(
            tenant_admin_payload,
            SUBJECT_KIND_SERVICE_ACCOUNT,
            SUBJECT_ID,
            issued.id,
            KeyUpdateRequest(scopes=["nope"]),
        )


async def test_revoke_by_subject_batch(oapi_db, redis_client, tenant_admin_payload):
    """AC-09: every key of the subject is revoked and each cached hash is deleted one by one (no SCAN)."""
    keys = [await _issue(tenant_admin_payload, name=f"k{i}") for i in range(3)]
    untouched = await _issue(tenant_admin_payload, subject_id="88888", name="other-subject")
    already = await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, keys[0].id)
    assert already.revoke_reason == REVOKE_REASON_MANUAL

    cache_keys = []
    for issued in keys:
        row = await _row(oapi_db, issued.id)
        cache_keys.append(CREDENTIAL_CACHE_KEY.format(row.token_hash))
        await redis_client.aset(cache_keys[-1], {"credential_id": issued.id}, expiration=300)

    count = await CredentialService.revoke_by_subject(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, reason=REVOKE_REASON_BATCH
    )
    assert count == 2  # the already-revoked row is not touched again

    rows = [await _row(oapi_db, issued.id) for issued in keys]
    assert all(row.revoked_at is not None for row in rows)
    assert [row.revoke_reason for row in rows] == [REVOKE_REASON_MANUAL, REVOKE_REASON_BATCH, REVOKE_REASON_BATCH]
    for cache_key in cache_keys:
        assert await redis_client.aget(cache_key) is None
    assert (await _row(oapi_db, untouched.id)).revoked_at is None


async def test_invalidate_subject_cache_keeps_rows(oapi_db, redis_client, tenant_admin_payload):
    """AC-21 / AC-47 support: disabling an account only drops cache entries; the key rows stay untouched."""
    issued = await _issue(tenant_admin_payload, name="stays")
    row = await _row(oapi_db, issued.id)
    cache_key = CREDENTIAL_CACHE_KEY.format(row.token_hash)
    await redis_client.aset(cache_key, {"credential_id": issued.id}, expiration=300)

    await CredentialService.invalidate_subject_cache(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, reason="subject_disabled"
    )
    assert await redis_client.aget(cache_key) is None
    after = await _row(oapi_db, issued.id)
    assert after.revoked_at is None and after.revoke_reason is None


# ---------------------------------------------------------------------------
# last-used throttle + lazy expiry
# ---------------------------------------------------------------------------


async def test_touch_last_used_throttled_60s(oapi_db, redis_client, tenant_admin_payload):
    """AC-10 / pit 20: one single-row UPDATE per 60s window, gated by ``SET NX EX 60``."""
    issued = await _issue(tenant_admin_payload, name="hot")

    assert await CredentialService.touch_last_used(issued.id) is True
    first = (await _row(oapi_db, issued.id)).last_used_at
    assert first is not None

    assert await CredentialService.touch_last_used(issued.id) is False
    assert (await _row(oapi_db, issued.id)).last_used_at == first

    throttle_key = LAST_USED_THROTTLE_KEY.format(issued.id)
    assert await redis_client.aget(throttle_key) is not None
    await redis_client.adelete(throttle_key)
    assert await CredentialService.touch_last_used(issued.id) is True
    assert (await _row(oapi_db, issued.id)).last_used_at >= first


async def test_expire_lazy_marks_reason_once(oapi_db, tenant_admin_payload):
    """AC-05 / AC-12: the first rejected call books ``expired``; a replay is a no-op (one audit row)."""
    issued = await _issue(tenant_admin_payload, name="stale", expires_at=datetime.now() - timedelta(minutes=1))

    assert await CredentialService.mark_expired_lazy(issued.id) is True
    assert await CredentialService.mark_expired_lazy(issued.id) is False

    row = await _row(oapi_db, issued.id)
    assert row.revoke_reason == REVOKE_REASON_EXPIRED
    assert row.revoked_at is None  # expiry stays distinguishable from a manual revoke (K3)
    assert not row.is_valid_at(datetime.now())

    expire_events = [entry for entry in await _audit_rows(oapi_db) if entry.action == "open_api.api_key.expire"]
    assert len(expire_events) == 1
    assert expire_events[0].operator_id == 0 and expire_events[0].operator_name == "system"


# ---------------------------------------------------------------------------
# audit (AC-12)
# ---------------------------------------------------------------------------


async def test_audit_events_never_contain_plaintext(oapi_db, redis_client, tenant_admin_payload):
    """AC-12: issue / update / revoke / revoke_all / expire each write an audit row carrying only the mask."""
    issued = await _issue(tenant_admin_payload, name="audited", scopes=["knowledge:read"])
    second = await _issue(tenant_admin_payload, name="audited-2", expires_at=datetime.now() - timedelta(minutes=1))
    await CredentialService.update(
        tenant_admin_payload,
        SUBJECT_KIND_SERVICE_ACCOUNT,
        SUBJECT_ID,
        issued.id,
        KeyUpdateRequest(scopes=["knowledge:write"]),
    )
    await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, issued.id)
    await CredentialService.mark_expired_lazy(second.id)
    await CredentialService.revoke_by_subject(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_ID, reason=REVOKE_REASON_BATCH
    )

    entries = await _audit_rows(oapi_db)
    actions = {entry.action for entry in entries}
    assert {
        "open_api.api_key.issue",
        "open_api.api_key.update",
        "open_api.api_key.revoke",
        "open_api.api_key.revoke_all",
        "open_api.api_key.expire",
    } <= actions

    blob = json.dumps([entry.model_dump(mode="json") for entry in entries])
    assert issued.plaintext not in blob and second.plaintext not in blob
    assert issued.plaintext.removeprefix(KEY_PREFIX) not in blob
    assert issued.key_mask in blob

    for entry in entries:
        if entry.action == "open_api.api_key.expire":
            continue
        assert entry.operator_id == tenant_admin_payload.user_id
        assert entry.operator_tenant_id == tenant_admin_payload.tenant_id
        assert entry.target_type == "api_key"
    issue_event = next(entry for entry in entries if entry.action == "open_api.api_key.issue")
    assert issue_event.audit_metadata["key_mask"] == issued.key_mask
    assert issue_event.audit_metadata["subject_id"] == SUBJECT_ID
    assert issue_event.audit_metadata["subject_kind"] == SUBJECT_KIND_SERVICE_ACCOUNT
