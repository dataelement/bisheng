"""Credential issuance, revocation, cache invalidation, and bookkeeping."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import datetime

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.open_api import (
    ApiCredentialNotFoundError,
    OpenApiDelegateConfigurationInvalidError,
    OpenApiExtensionScopeNotDeployedError,
    OpenApiUnknownScopeError,
    PersonalTokenScopeInvalidError,
    PersonalTokenTtlExceededError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.open_api.domain.models.api_credential import (
    CREDENTIAL_SUBJECT_KINDS,
    KEY_SECRET_LENGTH,
    PERSONAL_TOKEN_PREFIX,
    SERVICE_ACCOUNT_KEY_PREFIX,
    SUBJECT_KIND_NATURAL_PERSON,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    ApiCredential,
)
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.schemas.credential import KeyIssuedResponse, KeyIssueRequest, KeyItem, KeyUpdateRequest
from bisheng.open_api.domain.scopes import ISSUABLE_OPEN_API_SCOPE_CODES, OPEN_API_SCOPE_CODES
from bisheng.open_api.domain.services.delegate_scope_service import DelegateScopeService

CREDENTIAL_CACHE_KEY = "oapi:cred:{}"
LAST_USED_THROTTLE_KEY = "oapi:cred:lastused:{}"
LAST_USED_THROTTLE_SECONDS = 60


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def credential_prefix(subject_kind: str) -> str:
    if subject_kind == SUBJECT_KIND_SERVICE_ACCOUNT:
        return SERVICE_ACCOUNT_KEY_PREFIX
    if subject_kind == SUBJECT_KIND_NATURAL_PERSON:
        return PERSONAL_TOKEN_PREFIX
    raise ValueError(f"unsupported credential subject kind: {subject_kind!r}")


class CredentialService:
    @classmethod
    def validate_scopes(cls, scopes: list[str]) -> list[str]:
        for scope in scopes:
            if scope not in OPEN_API_SCOPE_CODES:
                raise OpenApiUnknownScopeError()
            if scope not in ISSUABLE_OPEN_API_SCOPE_CODES:
                raise OpenApiExtensionScopeNotDeployedError()
        return list(scopes)

    @classmethod
    async def issue(
        cls,
        *,
        tenant_id: int,
        subject_kind: str,
        subject_id: int,
        request: KeyIssueRequest,
        created_by: int | None,
        audit_operator=None,
    ) -> KeyIssuedResponse:
        if subject_kind not in CREDENTIAL_SUBJECT_KINDS:
            raise ValueError(f"unsupported credential subject kind: {subject_kind!r}")
        scopes = cls.validate_scopes(request.scopes)
        delegate_entries = await cls._delegate_entries(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            scopes=scopes,
            entries=request.delegate_scopes,
        )
        if subject_kind == SUBJECT_KIND_NATURAL_PERSON:
            await cls._validate_personal_token(scopes=scopes, expires_at=request.expires_at, tenant_id=tenant_id)
        prefix = credential_prefix(subject_kind)
        secret = secrets.token_urlsafe(32)
        if len(secret) != KEY_SECRET_LENGTH:  # pragma: no cover - Python contract guard
            raise RuntimeError("unexpected token_urlsafe output length")
        plaintext = f"{prefix}{secret}"
        row = await CredentialRepository.create_with_delegate_entries(
            ApiCredential(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                name=request.name,
                key_prefix=prefix,
                last4=plaintext[-4:],
                token_hash=hash_token(plaintext),
                scopes=scopes,
                expires_at=request.expires_at,
                created_by=created_by,
            ),
            delegate_entries,
        )
        if audit_operator is not None:
            await cls._audit(audit_operator, "open_api.api_key.create", row)
        item = await cls._to_item(row)
        return KeyIssuedResponse(**item.model_dump(), plaintext=plaintext)

    @classmethod
    async def list_by_subject(cls, subject_kind: str, subject_id: int) -> list[KeyItem]:
        rows = await CredentialRepository.list_by_subject(subject_kind, subject_id)
        moment = datetime.now()
        return [await cls._to_item(row, now=moment) for row in rows]

    @classmethod
    async def get_row(cls, subject_kind: str, subject_id: int, credential_id: int) -> ApiCredential:
        row = await CredentialRepository.get(credential_id)
        if row is None or row.subject_kind != subject_kind or row.subject_id != subject_id:
            raise ApiCredentialNotFoundError()
        return row

    @classmethod
    async def update(
        cls,
        subject_kind: str,
        subject_id: int,
        credential_id: int,
        request: KeyUpdateRequest,
        *,
        audit_operator=None,
    ) -> KeyItem:
        row = await cls.get_row(subject_kind, subject_id, credential_id)
        if request.name is not None:
            row.name = request.name
        if request.scopes is not None:
            row.scopes = cls.validate_scopes(request.scopes)
        if "expires_at" in request.model_fields_set:
            row.expires_at = request.expires_at
        if row.subject_kind == SUBJECT_KIND_NATURAL_PERSON:
            await cls._validate_personal_token(
                scopes=list(row.scopes or []),
                expires_at=row.expires_at,
                tenant_id=row.tenant_id,
            )
        current_entries = await DelegateScopeService.response_entries(row.id)
        if "delegate" not in (row.scopes or []):
            requested_entries = []
        else:
            requested_entries = (
                request.delegate_scopes if request.delegate_scopes is not None else current_entries
            )
        delegate_entries = await cls._delegate_entries(
            tenant_id=row.tenant_id,
            subject_kind=row.subject_kind,
            scopes=list(row.scopes or []),
            entries=requested_entries,
        )
        await CredentialRepository.save_with_delegate_entries(row, delegate_entries)
        await cls.invalidate_cache((row.token_hash,))
        if audit_operator is not None:
            await cls._audit(audit_operator, "open_api.api_key.update", row)
        return await cls._to_item(row)

    @classmethod
    async def revoke(
        cls,
        subject_kind: str,
        subject_id: int,
        credential_id: int,
        *,
        reason: str,
        audit_operator=None,
    ) -> KeyItem:
        row = await cls.get_row(subject_kind, subject_id, credential_id)
        if row.revoked_at is None:
            row.revoked_at = datetime.now()
            row.revoke_reason = reason
            await CredentialRepository.save(row)
        await cls.invalidate_cache((row.token_hash,))
        if audit_operator is not None:
            await cls._audit(audit_operator, "open_api.api_key.revoke", row)
        return await cls._to_item(row)

    @classmethod
    async def revoke_by_subject(
        cls,
        subject_kind: str,
        subject_id: int,
        *,
        reason: str,
        audit_operator=None,
    ) -> int:
        all_rows = await CredentialRepository.list_by_subject(subject_kind, subject_id)
        revoked = await CredentialRepository.revoke_subject(subject_kind, subject_id, reason=reason)
        await cls.invalidate_cache(row.token_hash for row in all_rows)
        if audit_operator is not None:
            for row in revoked:
                await cls._audit(audit_operator, "open_api.api_key.revoke", row)
        return len(revoked)

    @classmethod
    async def invalidate_subject_cache(cls, subject_kind: str, subject_id: int) -> int:
        rows = await CredentialRepository.list_by_subject(subject_kind, subject_id)
        return await cls.invalidate_cache(row.token_hash for row in rows)

    @classmethod
    async def invalidate_cache(cls, token_hashes: Iterable[str]) -> int:
        redis = await get_redis_client()
        deleted = 0
        for token_hash in token_hashes:
            deleted += bool(await redis.adelete(CREDENTIAL_CACHE_KEY.format(token_hash)))
        return deleted

    @classmethod
    async def touch_last_used(cls, credential_id: int) -> bool:
        try:
            redis = await get_redis_client()
            acquired = await redis.asetNx(
                LAST_USED_THROTTLE_KEY.format(credential_id),
                1,
                expiration=LAST_USED_THROTTLE_SECONDS,
            )
        except (RedisError, OSError) as exc:
            logger.warning("open_api last_used throttle unavailable for credential {}: {}", credential_id, exc)
            return False
        if not acquired:
            return False
        return await CredentialRepository.touch_last_used(credential_id, used_at=datetime.now())

    @staticmethod
    async def _audit(operator, action: str, row: ApiCredential) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=row.tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=get_current_tenant_id() or operator.tenant_id,
            action=action,
            target_type="api_credential",
            target_id=str(row.id),
            object_name=row.name,
            metadata={
                "credential_id": row.id,
                "subject_kind": row.subject_kind,
                "subject_id": row.subject_id,
                "scopes": list(row.scopes or []),
                "key_mask": row.key_mask,
            },
        )

    @staticmethod
    async def _to_item(row: ApiCredential, *, now: datetime | None = None) -> KeyItem:
        item = KeyItem.from_row(row, now=now)
        return item.model_copy(
            update={"delegate_scopes": await DelegateScopeService.response_entries(row.id)}
        )

    @staticmethod
    async def _delegate_entries(
        *,
        tenant_id: int,
        subject_kind: str,
        scopes: list[str],
        entries,
    ) -> tuple[tuple[str, int], ...]:
        has_delegate = "delegate" in scopes
        if subject_kind != SUBJECT_KIND_SERVICE_ACCOUNT and (has_delegate or entries):
            raise OpenApiDelegateConfigurationInvalidError()
        if has_delegate != bool(entries):
            raise OpenApiDelegateConfigurationInvalidError()
        if not has_delegate:
            return ()
        return await DelegateScopeService.validate_entries(tenant_id=tenant_id, entries=entries)

    @staticmethod
    async def _validate_personal_token(
        *,
        scopes: list[str],
        expires_at: datetime | None,
        tenant_id: int,
    ) -> None:
        if scopes != ["knowledge:read"]:
            raise PersonalTokenScopeInvalidError()
        from datetime import timedelta

        from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService

        policy = await TenantSettingService.get_policy(tenant_id)
        if expires_at is None or expires_at > datetime.now() + timedelta(days=policy.ttl_days):
            raise PersonalTokenTtlExceededError()
