"""Fail-closed validation of ``bs-sak-`` and ``bs-pat-`` credentials."""

from __future__ import annotations

import hmac
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from loguru import logger

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiCredentialInvalidError,
    OpenApiCredentialMissingError,
    PersonalTokenHolderInvalidError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.models.api_credential import (
    KEY_SECRET_LENGTH,
    PERSONAL_TOKEN_PREFIX,
    SERVICE_ACCOUNT_KEY_PREFIX,
    SUBJECT_KIND_NATURAL_PERSON,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    ApiCredential,
)
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.repositories.service_account_repository import ServiceAccountRepository
from bisheng.open_api.domain.services.credential_service import CREDENTIAL_CACHE_KEY, CredentialService, hash_token

_TOKEN_RE = re.compile(
    rf"^(?:{re.escape(SERVICE_ACCOUNT_KEY_PREFIX)}|{re.escape(PERSONAL_TOKEN_PREFIX)})"
    rf"[A-Za-z0-9_-]{{{KEY_SECRET_LENGTH}}}$"
)

SubjectResolver = Callable[[ApiCredential], Awaitable[OpenApiPrincipal]]


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise OpenApiCredentialMissingError()
    scheme, separator, plaintext = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not _TOKEN_RE.fullmatch(plaintext):
        raise OpenApiCredentialMissingError()
    return plaintext


async def resolve_service_account(row: ApiCredential) -> OpenApiPrincipal:
    account = await ServiceAccountRepository.get(row.subject_id)
    if account is None or not account.is_enabled or account.tenant_id != row.tenant_id:
        raise OpenApiCredentialInvalidError()
    return OpenApiPrincipal(
        credential_id=row.id,
        actor_kind="service_account",
        actor_id=account.id,
        actor_name=account.name,
        tenant_id=row.tenant_id,
        resource_owner_user_id=account.resource_owner_user_id,
        scopes=frozenset(row.scopes or []),
        mode="S",
        authorization_subject_type="service_account",
        authorization_subject_id=account.id,
        effective_user_id=None,
    )


async def resolve_natural_person(row: ApiCredential) -> OpenApiPrincipal:
    from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository

    holder = await OwnerRepository.get_active_natural_person(row.subject_id)
    if holder is None or holder.tenant_id != row.tenant_id:
        raise PersonalTokenHolderInvalidError()

    # A PAT inherits the holder's ordinary resource grants, not management
    # shortcuts. Administrator status is loaded separately by the issuance and
    # ledger services only to cap TTL and surface the mandatory risk warning.
    return OpenApiPrincipal(
        credential_id=row.id,
        actor_kind="natural_person",
        actor_id=row.subject_id,
        actor_name=holder.user_name,
        tenant_id=row.tenant_id,
        resource_owner_user_id=row.subject_id,
        scopes=frozenset(row.scopes or []),
        mode="S",
        authorization_subject_type="user",
        authorization_subject_id=row.subject_id,
        effective_user_id=row.subject_id,
    )


SUBJECT_RESOLVERS: dict[str, SubjectResolver] = {
    SUBJECT_KIND_SERVICE_ACCOUNT: resolve_service_account,
    SUBJECT_KIND_NATURAL_PERSON: resolve_natural_person,
}


def _prefix_matches_subject(plaintext: str, subject_kind: str) -> bool:
    return (subject_kind == SUBJECT_KIND_SERVICE_ACCOUNT and plaintext.startswith(SERVICE_ACCOUNT_KEY_PREFIX)) or (
        subject_kind == SUBJECT_KIND_NATURAL_PERSON and plaintext.startswith(PERSONAL_TOKEN_PREFIX)
    )


async def validate_bearer(authorization: str | None) -> OpenApiPrincipal:
    plaintext = extract_bearer_token(authorization)
    digest = hash_token(plaintext)
    try:
        redis = await get_redis_client()
        cached = await redis.aget(CREDENTIAL_CACHE_KEY.format(digest))
        if cached is not None:
            principal = OpenApiPrincipal.model_validate(cached)
            if not _prefix_matches_subject(plaintext, principal.actor_kind):
                raise OpenApiCredentialInvalidError()
        else:
            principal = await _resolve_from_database(plaintext, digest)
            ttl = int(settings.open_api.credential_cache_ttl_seconds)
            if ttl > 0:
                await redis.aset(
                    CREDENTIAL_CACHE_KEY.format(digest),
                    principal.model_dump(mode="json"),
                    expiration=ttl,
                )
        await _assert_tenant_active(principal.tenant_id, redis)
    except OpenApiAuthError:
        raise
    except Exception as exc:
        logger.opt(exception=True).warning("open_api credential validation dependency failed")
        raise OpenApiAuthDependencyUnavailableError() from exc

    try:
        await CredentialService.touch_last_used(principal.credential_id)
    except Exception:
        # Authentication has already completed. Usage telemetry is best-effort
        # and must not turn a valid credential into an availability failure.
        logger.opt(exception=True).warning("open_api last-used update failed")
    return principal


async def _resolve_from_database(plaintext: str, digest: str) -> OpenApiPrincipal:
    row = await CredentialRepository.get_by_hash(digest)
    now = datetime.now()
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        raise OpenApiCredentialInvalidError()
    if not _prefix_matches_subject(plaintext, row.subject_kind) or not row.is_valid_at(now):
        raise OpenApiCredentialInvalidError()
    resolver = SUBJECT_RESOLVERS.get(row.subject_kind)
    if resolver is None:
        raise OpenApiCredentialInvalidError()
    return await resolver(row)


async def _assert_tenant_active(tenant_id: int, redis) -> None:
    from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY

    if await redis.aget(DISABLED_TENANT_KEY.format(tenant_id)):
        raise OpenApiCredentialInvalidError()


__all__ = [
    "SUBJECT_RESOLVERS",
    "extract_bearer_token",
    "resolve_natural_person",
    "resolve_service_account",
    "validate_bearer",
]
