"""Validate a presented ``bs-sak-`` credential and build the acting identity (F049 design D2).

This is the single choke point behind every ``/api/v2`` request (HTTP and WS
alike). The order below is fixed — each step exists because skipping it has a
concrete failure mode:

1. **Extract the bearer** (26001). Query parameters are never accepted: they end
   up in access logs.
2. **Look the row up by ``sha256(plaintext)``** under ``bypass_tenant_filter()``
   (K6): there is no tenant context yet, and the row's own ``tenant_id`` is what
   seeds it.
3. **Compare the stored hash with ``hmac.compare_digest``** (precedent
   ``sso_sync/domain/services/hmac_auth.py:103``) — no ``==`` on secrets.
4. **Not revoked → not expired** (expired books ``revoke_reason='expired'`` once,
   then 26002).
5. **Dispatch on ``subject_kind``** through :data:`SUBJECT_RESOLVERS`. F049
   registers ``service_account`` only; a ``hosted_app`` credential is refused
   with 26002 until F055 registers its resolver — silently accepting it would
   invent an execution identity nobody defined.
6. **Cache the minimal payload** (``oapi:cred:{sha256}``, TTL ≤ 5s). Never a
   pickled ``UserPayload``: that would freeze an identity for the TTL window and
   bloat the value.
7. **Per request, cache hit included**: compare ``expires_at`` against now
   (AC-05 must hold inside the TTL window) and consult the disabled-tenant
   blacklist the tenant module writes.
8. **Seed both tenant ContextVars unconditionally** (pits 2 + 9). The HTTP
   middleware pre-seeds tenant 1 for any bearer it cannot decode and never sets
   ``visible_tenant_ids`` for us, so a child-tenant service account would
   silently read Root data / lose Root-shared resources.
9. **Build ``UserPayload`` directly** — never ``init_login_user`` (pit 4): it
   would run a Redis + FGA global-super probe per request and turn "a service
   account is never super" from a structural fact into a data state.

**Fail closed** (K2 / AC-34): any Redis or DB failure raises 26030 (HTTP 503).
There is no path in this module that answers "allow" when a dependency is down.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from loguru import logger
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiCredentialInvalidError,
    OpenApiCredentialMissingError,
    ServiceAccountInactiveError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    set_current_tenant_id,
    set_visible_tenant_ids,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import UserTenantDao
from bisheng.open_api.domain.context import (
    PRINCIPAL_KIND_SERVICE_ACCOUNT,
    OpenApiPrincipal,
    set_current_open_api_principal,
)
from bisheng.open_api.domain.models.api_credential import (
    KEY_PREFIX,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    ApiCredential,
    ApiCredentialDao,
)
from bisheng.open_api.domain.models.service_account import ServiceAccountDao
from bisheng.open_api.domain.services.credential_service import (
    CREDENTIAL_CACHE_KEY,
    CredentialService,
    hash_token,
)
from bisheng.user.domain.models.user import USER_TYPE_SERVICE, User

BEARER_SCHEME = "bearer"


class ValidatedCredential(NamedTuple):
    """What the router-level dependency needs after a credential checks out."""

    principal: OpenApiPrincipal
    user: UserPayload


@dataclass(frozen=True, slots=True)
class ResolvedSubject:
    """The identity a ``subject_kind`` resolver produces."""

    subject_user_id: int
    subject_name: str
    tenant_id: int
    resource_owner_user_id: int | None = None


SubjectResolver = Callable[[ApiCredential], Awaitable[ResolvedSubject]]


def extract_bearer_token(authorization: str | None) -> str:
    """Return the ``bs-sak-…`` plaintext or raise 26001.

    Anything that is not ``Authorization: Bearer bs-sak-<secret>`` — no header,
    another scheme, a JWT, an empty value — is "no credential presented", which
    keeps it distinguishable from "credential presented but unusable" (26002).
    """
    if not authorization:
        raise OpenApiCredentialMissingError()
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != BEARER_SCHEME:
        raise OpenApiCredentialMissingError()
    token = parts[1].strip()
    if not token.startswith(KEY_PREFIX) or len(token) <= len(KEY_PREFIX):
        raise OpenApiCredentialMissingError()
    return token


# ---------------------------------------------------------------------------
# Subject resolvers
# ---------------------------------------------------------------------------


async def _resolve_service_account(row: ApiCredential) -> ResolvedSubject:
    """``subject_id`` is the principal ``user.user_id`` of a service account (design D1)."""
    try:
        user_id = int(row.subject_id)
    except (TypeError, ValueError) as exc:
        raise OpenApiCredentialInvalidError() from exc

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            principal = (await session.exec(select(User).where(User.user_id == user_id))).first()
            # ``include_deleted``: a deleted account must produce 26027, not
            # "unknown subject" — the admin needs to see why it stopped working.
            account = await ServiceAccountDao.aget(session, user_id, include_deleted=True)

    if principal is None or principal.user_type != USER_TYPE_SERVICE or account is None:
        raise OpenApiCredentialInvalidError()
    if not account.is_enabled:
        raise ServiceAccountInactiveError()
    if int(account.tenant_id) != int(row.tenant_id):
        raise OpenApiCredentialInvalidError()

    active = await UserTenantDao.aget_active_user_tenant(user_id)
    if active is None or active.status != "active" or int(active.tenant_id) != int(row.tenant_id):
        # pit 7: tenant reconciliation moving a subject back to Root must break
        # the key loudly instead of silently widening its reach.
        raise OpenApiCredentialInvalidError()

    return ResolvedSubject(
        subject_user_id=user_id,
        subject_name=principal.user_name,
        tenant_id=int(row.tenant_id),
        resource_owner_user_id=int(account.resource_owner_user_id),
    )


#: ``subject_kind`` → resolver. F055 registers ``hosted_app`` here; until then
#: such a credential is storable and revocable but not usable (design D2).
SUBJECT_RESOLVERS: dict[str, SubjectResolver] = {
    SUBJECT_KIND_SERVICE_ACCOUNT: _resolve_service_account,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def validate_bearer(authorization: str | None) -> ValidatedCredential:
    """Validate the ``Authorization`` header value and install the acting identity.

    Side effects on success: tenant + visible-tenant ContextVars, the
    ``current_open_api_principal`` ContextVar and a throttled ``last_used_at``
    stamp. Raises a 260xx ``OpenApiAuthError`` on every failure.
    """
    plaintext = extract_bearer_token(authorization)
    token_hash = hash_token(plaintext)

    try:
        payload = await _read_cache(token_hash)
        if payload is None:
            payload = await _resolve_from_db(token_hash)
            await _write_cache(token_hash, payload)
    except OpenApiAuthError:
        raise
    except Exception as exc:
        # K2: Redis or DB trouble is a 503, never an implicit pass.
        logger.opt(exception=True).warning("open_api credential validation dependency failed")
        raise OpenApiAuthDependencyUnavailableError() from exc

    await _assert_still_valid(payload)

    tenant_id = int(payload["tenant_id"])
    set_current_tenant_id(tenant_id)
    set_visible_tenant_ids(_visible_tenant_ids(tenant_id))

    principal = OpenApiPrincipal(
        credential_id=payload["credential_id"],
        subject_kind=payload["subject_kind"],
        subject_user_id=payload["subject_user_id"],
        resource_owner_user_id=payload["resource_owner_user_id"],
        scopes=tuple(payload["scopes"] or ()),
    )
    user = UserPayload(
        user_id=payload["subject_user_id"],
        user_name=payload["subject_name"],
        user_role=[],
        tenant_id=tenant_id,
        token_version=0,
        is_global_super=False,
        open_api_principal=principal,
    )
    set_current_open_api_principal(principal)

    try:
        await CredentialService.touch_last_used(payload["credential_id"])
    except (SQLAlchemyError, RedisError, OSError) as exc:
        # Observability only (AC-10 explicitly allows coalescing) — a failed
        # stamp must not reject an otherwise valid call.
        logger.warning("open_api last_used stamp failed for credential {}: {}", payload["credential_id"], exc)

    return ValidatedCredential(principal=principal, user=user)


async def _resolve_from_db(token_hash: str) -> dict[str, Any]:
    now = datetime.now()
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            row = await ApiCredentialDao.aget_by_hash(session, token_hash)
    if row is None:
        raise OpenApiCredentialInvalidError()
    if not hmac.compare_digest(row.token_hash, token_hash):
        raise OpenApiCredentialInvalidError()
    if row.revoked_at is not None:
        raise OpenApiCredentialInvalidError()
    if row.expires_at is not None and row.expires_at <= now:
        await CredentialService.mark_expired_lazy(row.id)
        raise OpenApiCredentialInvalidError()

    resolver = SUBJECT_RESOLVERS.get(row.subject_kind)
    if resolver is None:
        raise OpenApiCredentialInvalidError()
    subject = await resolver(row)

    return {
        "credential_id": int(row.id),
        "tenant_id": int(row.tenant_id),
        "subject_kind": row.subject_kind,
        "subject_user_id": subject.subject_user_id,
        "subject_name": subject.subject_name,
        "resource_owner_user_id": subject.resource_owner_user_id,
        "scopes": list(row.scopes or []),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


async def _assert_still_valid(payload: dict[str, Any]) -> None:
    """The two checks that run on **every** request, cache hit included."""
    expires_at = payload.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.now():
        # AC-05: a key that reaches its expiry inside the TTL window is rejected
        # by this comparison, not by cache eviction.
        try:
            await CredentialService.mark_expired_lazy(payload["credential_id"])
        except (SQLAlchemyError, RedisError, OSError) as exc:
            # Bookkeeping only; the rejection below stands either way.
            logger.warning("open_api lazy expiry bookkeeping failed: {}", exc)
        raise OpenApiCredentialInvalidError()

    try:
        from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY

        redis = await get_redis_client()
        blacklisted = await redis.aget(DISABLED_TENANT_KEY.format(int(payload["tenant_id"])))
    except Exception as exc:
        logger.opt(exception=True).warning("open_api tenant blacklist check failed")
        raise OpenApiAuthDependencyUnavailableError() from exc
    if blacklisted:
        # The tenant is disabled or archived: its credentials are unusable.
        # Reported as 26002 rather than a tenant-specific code so the open face
        # never tells an anonymous caller which tenant a key belongs to.
        raise OpenApiCredentialInvalidError()


def _visible_tenant_ids(tenant_id: int) -> frozenset[int]:
    """Replica of ``utils/http_middleware._compute_visible_tenant_ids`` for a non-super subject.

    Kept as a local copy on purpose: importing the middleware into a domain
    service would drag the whole FastAPI middleware stack in. The global-super
    branch is unreachable here — an open API principal is structurally never
    super (pit 4) — so only the Root / child cases remain.
    """
    if tenant_id == DEFAULT_TENANT_ID:
        return frozenset({DEFAULT_TENANT_ID})
    if tenant_id and tenant_id > 0:
        return frozenset({tenant_id, DEFAULT_TENANT_ID})
    return frozenset()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


async def _read_cache(token_hash: str) -> dict[str, Any] | None:
    redis = await get_redis_client()
    cached = await redis.aget(CREDENTIAL_CACHE_KEY.format(token_hash))
    return cached if isinstance(cached, dict) else None


async def _write_cache(token_hash: str, payload: dict[str, Any]) -> None:
    ttl = int(settings.open_api.credential_cache_ttl_seconds)
    if ttl <= 0:
        return  # caching disabled: every request goes to the DB
    redis = await get_redis_client()
    await redis.aset(CREDENTIAL_CACHE_KEY.format(token_hash), payload, expiration=ttl)


__all__ = [
    "PRINCIPAL_KIND_SERVICE_ACCOUNT",
    "SUBJECT_RESOLVERS",
    "ResolvedSubject",
    "ValidatedCredential",
    "extract_bearer_token",
    "validate_bearer",
]
