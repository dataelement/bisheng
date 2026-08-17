"""``credential_validator`` unit + integration tests (F049 T011, pairs with T012).

Test-First: written before
``open_api/domain/services/credential_validator.py``. This is the single
choke point every ``/api/v2`` request goes through, so the assertions are about
*order* and *failure direction* as much as about outcomes: unknown → 401 without
a timing signal, expired → rejected even on a cache hit, any infrastructure
wobble → 503 rather than a pass.

覆盖 AC: AC-01 (no valid credential → rejected), AC-03 (revoked within 5s),
AC-05 (expiry enforced per request), AC-21 / AC-47 (disabled or deleted subject
rejected), AC-32 (tenant context + visible tenants + directly built
``UserPayload``), AC-34 (fail closed on dependency failure).
"""

from __future__ import annotations

import hmac as hmac_module
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiCredentialInvalidError,
    OpenApiCredentialMissingError,
    ServiceAccountInactiveError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    get_current_tenant_id,
    get_visible_tenant_ids,
    set_current_tenant_id,
)
from bisheng.open_api.domain.context import (
    PRINCIPAL_KIND_SERVICE_ACCOUNT,
    get_current_open_api_principal,
)
from bisheng.open_api.domain.models.api_credential import (
    SUBJECT_KIND_HOSTED_APP,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    ApiCredential,
    ApiCredentialDao,
)
from bisheng.open_api.domain.services import credential_validator as validator_module
from bisheng.open_api.domain.services.credential_service import CREDENTIAL_CACHE_KEY, CredentialService
from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS, validate_bearer
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from test.open_api.conftest import ROOT_TENANT_ID


def _bearer(issued) -> str:
    return f"Bearer {issued.plaintext}"


async def _token_hash(oapi_db, credential_id: int) -> str:
    async with oapi_db() as session:
        return (await ApiCredentialDao.aget(session, credential_id)).token_hash


async def _row(oapi_db, credential_id: int) -> ApiCredential:
    async with oapi_db() as session:
        return await ApiCredentialDao.aget(session, credential_id)


# ---------------------------------------------------------------------------
# Bearer extraction + unknown credential (AC-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "   ",
        "bs-sak-abc",  # no scheme
        "Token bs-sak-abc",  # wrong scheme
        "Bearer ",  # empty value
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",  # a JWT is not a credential here
        "Bearer bs-sak-",  # prefix only
    ],
)
async def test_missing_or_malformed_bearer_26001(oapi_db, redis_client, header):
    """AC-01: nothing that is not a well-formed ``bs-sak-`` bearer gets past the door."""
    with pytest.raises(OpenApiCredentialMissingError) as excinfo:
        await validate_bearer(header)
    assert excinfo.value.code == 26001
    assert excinfo.value.http_status == 401


async def test_unknown_hash_26002(oapi_db, redis_client):
    """AC-01: a well-formed but unknown key is 26002 (401) — distinct from "no credential"."""
    with pytest.raises(OpenApiCredentialInvalidError) as excinfo:
        await validate_bearer("Bearer bs-sak-" + "A" * 43)
    assert excinfo.value.code == 26002 and excinfo.value.http_status == 401
    # No row exists, so there is nothing to compare; the constant-time assertion
    # lives in the happy path below, where a stored hash is actually verified.


async def test_happy_path_uses_constant_time_compare(
    oapi_db, redis_client, service_account_factory, credential_factory, monkeypatch
):
    """The stored hash is compared with ``hmac.compare_digest`` (precedent: hmac_auth.py:103)."""
    account = await service_account_factory("cmp")
    issued = await credential_factory(account.user_id)

    calls: list[tuple[str, str]] = []
    real_compare = hmac_module.compare_digest

    def _spy(left, right):
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(validator_module.hmac, "compare_digest", _spy)
    await validate_bearer(_bearer(issued))
    assert calls, "the stored token_hash must be verified with hmac.compare_digest"


# ---------------------------------------------------------------------------
# Revocation / expiry (AC-03 / AC-05)
# ---------------------------------------------------------------------------


async def test_revoked_rejected_within_5s(
    oapi_db, redis_client, tenant_admin_payload, service_account_factory, credential_factory
):
    """AC-03: revoke deletes the cache entry, so the very next call fails — no TTL wait."""
    account = await service_account_factory("revoked-soon")
    issued = await credential_factory(account.user_id)

    validated = await validate_bearer(_bearer(issued))
    assert validated.principal.credential_id == issued.id
    cache_key = CREDENTIAL_CACHE_KEY.format(await _token_hash(oapi_db, issued.id))
    assert await redis_client.aget(cache_key) is not None

    await CredentialService.revoke(tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id), issued.id)
    assert await redis_client.aget(cache_key) is None
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(_bearer(issued))

    # Second mechanism behind the 5s bound: even a cache entry that survived an
    # invalidation (multi-node race) cannot outlive the capped TTL.
    assert settings.open_api.credential_cache_ttl_seconds <= 5


async def test_expired_rejected_even_when_cache_hit(
    oapi_db, redis_client, service_account_factory, credential_factory, monkeypatch
):
    """AC-05: ``expires_at`` lives in the cached payload and is compared on every request."""
    account = await service_account_factory("expiring")
    issued = await credential_factory(account.user_id, expires_at=datetime.now() + timedelta(days=1))
    await validate_bearer(_bearer(issued))  # populate the cache

    cache_key = CREDENTIAL_CACHE_KEY.format(await _token_hash(oapi_db, issued.id))
    cached = await redis_client.aget(cache_key)
    assert cached is not None
    # Only the cached copy expires; the DB row stays valid, so a rejection can
    # come from the cache-hit comparison and from nowhere else.
    cached["expires_at"] = (datetime.now() - timedelta(seconds=1)).isoformat()
    await redis_client.aset(cache_key, cached, expiration=300)

    marked: list[int] = []

    async def _mark(credential_id: int) -> bool:
        marked.append(credential_id)
        return True

    monkeypatch.setattr(CredentialService, "mark_expired_lazy", _mark)
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(_bearer(issued))
    assert marked == [issued.id]
    assert (await _row(oapi_db, issued.id)).expires_at > datetime.now()


async def test_expired_row_marks_reason_and_rejects(oapi_db, redis_client, service_account_factory, credential_factory):
    """AC-05 / AC-12: the DB path books ``revoke_reason='expired'`` on the first rejection."""
    account = await service_account_factory("already-expired")
    issued = await credential_factory(account.user_id, expires_at=datetime.now() - timedelta(minutes=5))

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(_bearer(issued))
    row = await _row(oapi_db, issued.id)
    assert row.revoke_reason == "expired" and row.revoked_at is None
    assert await redis_client.aget(CREDENTIAL_CACHE_KEY.format(row.token_hash)) is None


# ---------------------------------------------------------------------------
# Subject resolution (AC-21 / AC-47)
# ---------------------------------------------------------------------------


async def test_subject_disabled_or_deleted_rejected_26027(
    oapi_db, redis_client, tenant_admin_payload, service_account_factory, credential_factory
):
    """AC-21 / AC-47: either lifecycle timestamp makes every key of the subject fail with 26027."""
    account = await service_account_factory("switchable")
    issued = await credential_factory(account.user_id)
    assert (await validate_bearer(_bearer(issued))).principal.subject_user_id == account.user_id

    await ServiceAccountService.disable(tenant_admin_payload, account.user_id)
    with pytest.raises(ServiceAccountInactiveError) as excinfo:
        await validate_bearer(_bearer(issued))
    assert excinfo.value.code == 26027

    await ServiceAccountService.enable(tenant_admin_payload, account.user_id)
    assert (await validate_bearer(_bearer(issued))).principal.credential_id == issued.id

    await ServiceAccountService.delete(tenant_admin_payload, account.user_id)
    with pytest.raises((ServiceAccountInactiveError, OpenApiCredentialInvalidError)):
        await validate_bearer(_bearer(issued))


async def test_subject_tenant_mismatch_rejected(
    oapi_db, redis_client, sub_tenant, tenant_admin_payload, service_account_factory, credential_factory
):
    """spec §3: any cross-tenant combination is refused; the key's tenant must be the subject's."""
    account = await service_account_factory(
        "child-bot",
        resource_owner_user_id=sub_tenant.admin_user_id,
        operator=sub_tenant.admin_payload,
    )
    assert account.tenant_id == sub_tenant.tenant_id

    # Issue the key while acting in Root — the credential row lands in tenant 1
    # while its subject lives in tenant 2.
    set_current_tenant_id(ROOT_TENANT_ID)
    mismatched = await credential_factory(account.user_id, operator=tenant_admin_payload)
    assert (await _row(oapi_db, mismatched.id)).tenant_id == ROOT_TENANT_ID

    with pytest.raises(OpenApiCredentialInvalidError) as excinfo:
        await validate_bearer(_bearer(mismatched))
    assert excinfo.value.code == 26002


async def test_hosted_app_without_resolver_26002(oapi_db, redis_client, credential_factory):
    """D2: F049 registers ``service_account`` only — a ``hosted_app`` key is refused until F055."""
    assert set(SUBJECT_RESOLVERS) == {SUBJECT_KIND_SERVICE_ACCOUNT}
    issued = await credential_factory("app-42", subject_kind=SUBJECT_KIND_HOSTED_APP)
    with pytest.raises(OpenApiCredentialInvalidError) as excinfo:
        await validate_bearer(_bearer(issued))
    assert excinfo.value.code == 26002


# ---------------------------------------------------------------------------
# Identity + tenant context (AC-32)
# ---------------------------------------------------------------------------


async def test_sets_tenant_context_and_visible_tenants(
    oapi_db, redis_client, sub_tenant, service_account_factory, credential_factory
):
    """AC-32 / pits 2 + 9: the dependency seeds both tenant ContextVars itself."""
    root_account = await service_account_factory("root-bot")
    root_key = await credential_factory(root_account.user_id)

    set_current_tenant_id(999)  # a stale value the validator must overwrite unconditionally
    await validate_bearer(_bearer(root_key))
    assert get_current_tenant_id() == ROOT_TENANT_ID
    assert get_visible_tenant_ids() == frozenset({ROOT_TENANT_ID})

    child_account = await service_account_factory(
        "child-bot",
        resource_owner_user_id=sub_tenant.admin_user_id,
        operator=sub_tenant.admin_payload,
    )
    set_current_tenant_id(sub_tenant.tenant_id)
    child_key = await credential_factory(child_account.user_id, operator=sub_tenant.admin_payload)

    set_current_tenant_id(ROOT_TENANT_ID)
    await validate_bearer(_bearer(child_key))
    assert get_current_tenant_id() == sub_tenant.tenant_id
    # Own leaf plus Root — the same rule JWT users get from _compute_visible_tenant_ids.
    assert get_visible_tenant_ids() == frozenset({sub_tenant.tenant_id, ROOT_TENANT_ID})


async def test_user_payload_constructed_directly(
    oapi_db, redis_client, human_user, service_account_factory, credential_factory, monkeypatch
):
    """AC-32 / pit 4: no ``init_login_user`` — global-super stays a structural False."""
    from bisheng.user.domain.services.auth import LoginUser

    async def _forbidden(*args, **kwargs):
        raise AssertionError("init_login_user must never run on the open API path")

    monkeypatch.setattr(LoginUser, "init_login_user", classmethod(_forbidden))
    monkeypatch.setattr(LoginUser, "init_login_user_sync", classmethod(_forbidden))

    account = await service_account_factory("payload-bot")
    issued = await credential_factory(account.user_id, scopes=["knowledge:read"])
    validated = await validate_bearer(_bearer(issued))

    user = validated.user
    assert user.user_id == account.user_id
    assert user.user_role == [] and user.is_global_super is False and user.token_version == 0
    assert user.tenant_id == ROOT_TENANT_ID
    assert user.is_admin() is False

    principal = validated.principal
    assert principal is user.open_api_principal
    assert principal.subject_kind == PRINCIPAL_KIND_SERVICE_ACCOUNT
    assert principal.credential_id == issued.id
    assert principal.subject_user_id == account.user_id
    assert principal.resource_owner_user_id == human_user.user_id
    assert principal.scopes == ("knowledge:read",)
    assert principal.has_scope("knowledge:read") and not principal.has_scope("knowledge:write")
    assert get_current_open_api_principal() == principal


async def test_cache_payload_minimal_not_pickled_userpayload(
    oapi_db, redis_client, human_user, service_account_factory, credential_factory
):
    """D2: the cached value is a small dict — never a pickled ``UserPayload`` / ORM row."""
    account = await service_account_factory("cache-shape")
    issued = await credential_factory(account.user_id, scopes=["workflow:invoke"])
    await validate_bearer(_bearer(issued))

    cached = await redis_client.aget(CREDENTIAL_CACHE_KEY.format(await _token_hash(oapi_db, issued.id)))
    assert isinstance(cached, dict)
    assert set(cached) == {
        "credential_id",
        "tenant_id",
        "subject_kind",
        "subject_user_id",
        "subject_name",
        "resource_owner_user_id",
        "scopes",
        "expires_at",
    }
    assert all(isinstance(value, (int, str, list, type(None))) for value in cached.values())
    assert cached["scopes"] == ["workflow:invoke"]
    assert cached["resource_owner_user_id"] == human_user.user_id


# ---------------------------------------------------------------------------
# Fail closed (AC-34) + tenant blacklist
# ---------------------------------------------------------------------------


async def test_redis_down_fail_closed_26030(
    oapi_db, redis_client, service_account_factory, credential_factory, monkeypatch
):
    """AC-34 / K2: a Redis failure rejects with 503 — it never falls through to "allow"."""
    account = await service_account_factory("redis-down")
    issued = await credential_factory(account.user_id)

    async def _boom():
        raise ConnectionError("redis is gone")

    monkeypatch.setattr(validator_module, "get_redis_client", _boom)
    with pytest.raises(OpenApiAuthDependencyUnavailableError) as excinfo:
        await validate_bearer(_bearer(issued))
    assert excinfo.value.code == 26030 and excinfo.value.http_status == 503


async def test_db_down_fail_closed_26030(
    oapi_db, redis_client, service_account_factory, credential_factory, monkeypatch
):
    """AC-34 / K2: same for the credential lookup — no cached "unknown" and no pass-through."""
    account = await service_account_factory("db-down")
    issued = await credential_factory(account.user_id)

    async def _boom(*args, **kwargs):
        raise RuntimeError("connection pool exhausted")

    monkeypatch.setattr(ApiCredentialDao, "aget_by_hash", classmethod(_boom))
    with pytest.raises(OpenApiAuthDependencyUnavailableError) as excinfo:
        await validate_bearer(_bearer(issued))
    assert excinfo.value.code == 26030


async def test_disabled_tenant_blacklist_rejects(oapi_db, redis_client, service_account_factory, credential_factory):
    """A disabled / archived tenant is checked on every request (the key that tenant_service writes)."""
    from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY

    account = await service_account_factory("tenant-off")
    issued = await credential_factory(account.user_id)
    await validate_bearer(_bearer(issued))

    await redis_client.aset(DISABLED_TENANT_KEY.format(ROOT_TENANT_ID), 1, expiration=300)
    try:
        with pytest.raises(OpenApiCredentialInvalidError):
            await validate_bearer(_bearer(issued))
    finally:
        await redis_client.adelete(DISABLED_TENANT_KEY.format(ROOT_TENANT_ID))


async def test_last_used_touched_on_success(oapi_db, redis_client, service_account_factory, credential_factory):
    """AC-10: a successful validation stamps the key (throttled); a rejected one never does."""
    account = await service_account_factory("touched")
    issued = await credential_factory(account.user_id)

    await validate_bearer(_bearer(issued))
    assert (await _row(oapi_db, issued.id)).last_used_at is not None

    other = await credential_factory(account.user_id, name="never-used")
    with pytest.raises(OpenApiCredentialMissingError):
        await validate_bearer("Bearer nope")
    async with oapi_db() as session:
        untouched = (await session.exec(select(ApiCredential).where(ApiCredential.id == other.id))).first()
    assert untouched.last_used_at is None
