"""Credential (``bs-sak-``) lifecycle: issue / edit / revoke / batch revoke / bookkeeping.

Design anchors (F049 design D2 / D10 / D11, pits K1 / K3 / K6 / K7 / 17 / 20):

* **Plaintext leaves exactly once** — :meth:`CredentialService.issue` returns it
  inside ``KeyIssuedResponse``; the row stores only ``sha256(plaintext)`` plus
  ``key_prefix`` / ``last4`` for the mask. Audit metadata carries the mask.
* **Secret generation is ``secrets.token_urlsafe(32)``** (43 urlsafe chars), not
  ``generate_short_high_entropy_string`` — that helper silently truncates at ~43
  characters, so a "64-char key" would be a documentation lie (pit 17).
* **Cache invalidation is active, not TTL-based** (K1): every write deletes the
  ``oapi:cred:{sha256}`` keys of the affected rows one by one, from the DB
  listing — never ``SCAN`` (K7). The TTL only covers the multi-node window where
  a delete races an in-flight request.
* **Writes are single-row ORM** (K6): the tenant filter rewrites SELECTs only, so
  a bulk ``UPDATE`` would silently cross tenants. The one conditional statement
  (:meth:`ApiCredentialDao.amark_expired`) is pinned to a primary key.
* **``last_used_at`` is throttled by a 60s Redis latch** (pit 20): unthrottled
  per-request UPDATEs blow up DM8's undo segment — AC-10 explicitly allows the
  write coalescing.

Scope validation order matters: ``delegate`` is checked before "unknown" so the
rejection can be specific (26024, "delegation ships with F050") instead of the
generic 26025.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.open_api import (
    ApiCredentialNotFoundError,
    OpenApiDelegateScopeNotEnabledError,
    OpenApiExtensionScopeNotDeployedError,
    OpenApiUnknownScopeError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.open_api.domain.models.api_credential import (
    CREDENTIAL_SUBJECT_KINDS,
    KEY_PREFIX,
    REVOKE_REASON_BATCH,
    REVOKE_REASON_EXPIRED,
    REVOKE_REASON_MANUAL,
    ApiCredential,
    ApiCredentialDao,
    mask_key,
)
from bisheng.open_api.domain.schemas.credential import (
    KeyIssuedResponse,
    KeyIssueRequest,
    KeyItem,
    KeyUpdateRequest,
)
from bisheng.open_api.domain.scopes import (
    DELEGATE_SCOPE_CODE,
    is_known_scope,
    is_toolkit_scope,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import of the user domain
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.open_api.domain.schemas.credential import WhoamiResourceOwner

# Redis keys (design D2). ``{}`` is filled with sha256(plaintext) / credential id.
CREDENTIAL_CACHE_KEY = "oapi:cred:{}"
LAST_USED_THROTTLE_KEY = "oapi:cred:lastused:{}"
LAST_USED_THROTTLE_SECONDS = 60

AUDIT_TARGET_TYPE = "api_key"
AUDIT_ACTION_ISSUE = "open_api.api_key.issue"
AUDIT_ACTION_UPDATE = "open_api.api_key.update"
AUDIT_ACTION_REVOKE = "open_api.api_key.revoke"
AUDIT_ACTION_REVOKE_ALL = "open_api.api_key.revoke_all"
AUDIT_ACTION_EXPIRE = "open_api.api_key.expire"
AUDIT_ACTION_INVALIDATE_BY_SUBJECT = "open_api.api_key.invalidate_by_subject"


def hash_token(plaintext: str) -> str:
    """The only stored form of a credential."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    """Audit metadata goes into a JSON column — datetimes must be strings."""
    return value.isoformat() if value is not None else None


class CredentialService:
    """Everything that writes ``api_credential``. Validation of a presented key lives in
    ``credential_validator`` — this class never sees an incoming request."""

    # ------------------------------------------------------------------
    # Scope validation (AC-06 / AC-13 / AC-14)
    # ------------------------------------------------------------------

    @classmethod
    def validate_scopes(cls, scopes: Sequence[str]) -> list[str]:
        """Return the accepted scope list or raise 26024 / 26025 / 26023."""
        accepted: list[str] = []
        toolkit_enabled = bool(settings.open_platform.enabled)
        for code in scopes:
            if code == DELEGATE_SCOPE_CODE:
                # Recognised on purpose so the message can say "not enabled yet"
                # rather than "unknown scope" (AC-14).
                raise OpenApiDelegateScopeNotEnabledError()
            if not is_known_scope(code):
                raise OpenApiUnknownScopeError()
            if is_toolkit_scope(code) and not toolkit_enabled:
                raise OpenApiExtensionScopeNotDeployedError()
            accepted.append(code)
        return accepted

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @classmethod
    async def _list_rows(cls, subject_kind: str, subject_id: str) -> list[ApiCredential]:
        async with get_async_db_session() as session:
            return await ApiCredentialDao.alist_by_subject(session, subject_kind, str(subject_id))

    @classmethod
    async def list_by_subject(
        cls,
        subject_kind: str,
        subject_id: str,
        *,
        now: datetime | None = None,
    ) -> list[KeyItem]:
        """Masked view of every key of one subject, newest first (AC-44)."""
        moment = now or datetime.now()
        rows = await cls._list_rows(subject_kind, subject_id)
        return [KeyItem.from_row(row, now=moment) for row in rows]

    @classmethod
    async def get_row(cls, subject_kind: str, subject_id: str, credential_id: int) -> ApiCredential:
        """One key, scoped to its owning subject — a foreign key id is 26026, never a silent hit."""
        async with get_async_db_session() as session:
            row = await ApiCredentialDao.aget(session, credential_id)
        if row is None or row.subject_kind != subject_kind or row.subject_id != str(subject_id):
            raise ApiCredentialNotFoundError()
        return row

    @classmethod
    async def get_resource_owner(cls, owner_user_id: int | None) -> WhoamiResourceOwner | None:
        """The person resources created through a credential belong to (AC-24).

        Lives here rather than in the endpoint so the API layer does not reach
        into another module's model layer (arch-guard RULE-3/RULE-5).

        Returns ``None`` for a missing, deleted or otherwise unresolvable owner
        instead of raising: the only caller is ``whoami``, whose job is to
        describe the credential. A dangling owner reference is a fact about the
        account worth surfacing as "unknown", not a reason to refuse to answer
        what the key is — refusing would turn a cosmetic data problem into
        "your key does not work".
        """
        if owner_user_id is None:
            return None
        from bisheng.open_api.domain.schemas.credential import WhoamiResourceOwner
        from bisheng.user.domain.models.user import UserDao

        owner = await UserDao.aget_user(owner_user_id)
        if owner is None:
            logger.warning(f"open_api.whoami resource_owner_user_id={owner_user_id} no longer resolves to a user")
            return None
        return WhoamiResourceOwner(user_id=owner.user_id, user_name=owner.user_name)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @classmethod
    async def issue(
        cls,
        operator: UserPayload,
        subject_kind: str,
        subject_id: str,
        request: KeyIssueRequest,
    ) -> KeyIssuedResponse:
        """Mint a credential. The returned ``plaintext`` is the only copy that ever exists (AC-02)."""
        if subject_kind not in CREDENTIAL_SUBJECT_KINDS:
            # Callers are endpoints with fixed kinds; anything else is a bug.
            raise ValueError(f"{subject_kind!r} cannot own an api_credential row")
        scopes = cls.validate_scopes(request.scopes)

        secret = secrets.token_urlsafe(32)
        plaintext = f"{KEY_PREFIX}{secret}"
        tenant_id = cls._acting_tenant_id(operator)
        row = ApiCredential(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=str(subject_id),
            name=request.name,
            key_prefix=KEY_PREFIX,
            last4=plaintext[-4:],
            token_hash=hash_token(plaintext),
            scopes=scopes,
            expires_at=request.expires_at,
            created_by=operator.user_id,
        )
        async with get_async_db_session() as session:
            await ApiCredentialDao.acreate(session, row)
            await session.commit()
            await session.refresh(row)

        # A brand-new hash cannot be cached, so no invalidation is needed here.
        await cls._audit(operator, AUDIT_ACTION_ISSUE, row)
        item = KeyItem.from_row(row, now=datetime.now())
        return KeyIssuedResponse(**item.model_dump(), plaintext=plaintext)

    @classmethod
    async def update(
        cls,
        operator: UserPayload,
        subject_kind: str,
        subject_id: str,
        credential_id: int,
        request: KeyUpdateRequest,
    ) -> KeyItem:
        """Edit name / scopes / expiry of an existing key — same key, effective immediately (AC-08)."""
        row = await cls.get_row(subject_kind, subject_id, credential_id)
        fields = request.model_fields_set
        before = {"name": row.name, "scopes": list(row.scopes or []), "expires_at": _iso(row.expires_at)}

        if request.scopes is not None:
            row.scopes = cls.validate_scopes(request.scopes)
        if request.name is not None:
            row.name = request.name
        if "expires_at" in fields:
            # An explicit null clears the expiry; an absent field keeps it.
            row.expires_at = request.expires_at

        async with get_async_db_session() as session:
            session.add(row)
            await ApiCredentialDao.aupdate_row(session, row)
            await session.commit()
            await session.refresh(row)

        await cls.invalidate_cache([row.token_hash])
        after = {"name": row.name, "scopes": list(row.scopes or []), "expires_at": _iso(row.expires_at)}
        await cls._audit(operator, AUDIT_ACTION_UPDATE, row, extra={"before": before, "after": after})
        return KeyItem.from_row(row, now=datetime.now())

    @classmethod
    async def revoke(
        cls,
        operator: UserPayload,
        subject_kind: str,
        subject_id: str,
        credential_id: int,
        *,
        reason: str = REVOKE_REASON_MANUAL,
    ) -> KeyItem:
        """Soft revoke (AC-11): the row, its subject and its issuer stay for audit."""
        row = await cls.get_row(subject_kind, subject_id, credential_id)
        if row.revoked_at is None:
            row.revoked_at = datetime.now()
            row.revoke_reason = reason
            async with get_async_db_session() as session:
                session.add(row)
                await ApiCredentialDao.aupdate_row(session, row)
                await session.commit()
                await session.refresh(row)

        await cls.invalidate_cache([row.token_hash])
        await cls._audit(operator, AUDIT_ACTION_REVOKE, row, extra={"reason": reason})
        return KeyItem.from_row(row, now=datetime.now())

    @classmethod
    async def revoke_by_subject(
        cls,
        operator: UserPayload,
        subject_kind: str,
        subject_id: str,
        *,
        reason: str = REVOKE_REASON_BATCH,
    ) -> int:
        """Revoke every still-valid key of one subject and drop all its cache entries (AC-09 / AC-21).

        Already-revoked rows keep their original ``revoke_reason`` — the history
        of *why* a key died is part of the audit trail (AC-11).
        """
        rows = await cls._list_rows(subject_kind, subject_id)
        pending = [row for row in rows if row.revoked_at is None]
        now = datetime.now()
        if pending:
            async with get_async_db_session() as session:
                for row in pending:
                    row.revoked_at = now
                    row.revoke_reason = reason
                    session.add(row)
                    await ApiCredentialDao.aupdate_row(session, row)
                await session.commit()

        await cls.invalidate_cache([row.token_hash for row in rows])
        action = AUDIT_ACTION_REVOKE_ALL if reason == REVOKE_REASON_BATCH else AUDIT_ACTION_INVALIDATE_BY_SUBJECT
        await cls._audit_subject(
            operator,
            action,
            subject_kind,
            subject_id,
            rows,
            extra={"reason": reason, "revoked_count": len(pending)},
        )
        return len(pending)

    @classmethod
    async def invalidate_subject_cache(
        cls,
        operator: UserPayload,
        subject_kind: str,
        subject_id: str,
        *,
        reason: str,
    ) -> int:
        """Drop the cache entries of every key of one subject **without touching the rows**.

        Used when the subject itself becomes unusable (service account disabled):
        the keys must stop working within 5s (AC-21 / AC-47), but re-enabling has
        to restore them unchanged, so ``revoked_at`` / ``revoke_reason`` stay put.
        """
        rows = await cls._list_rows(subject_kind, subject_id)
        deleted = await cls.invalidate_cache([row.token_hash for row in rows])
        await cls._audit_subject(
            operator,
            AUDIT_ACTION_INVALIDATE_BY_SUBJECT,
            subject_kind,
            subject_id,
            rows,
            extra={"reason": reason, "invalidated_count": deleted},
        )
        return deleted

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    @classmethod
    async def touch_last_used(cls, credential_id: int) -> bool:
        """Stamp ``last_used_at`` at most once per 60s (AC-10). Returns True when it wrote.

        Best-effort by design: a Redis hiccup must not fail an otherwise valid
        call — the stamp is an observability aid, not an authorisation input.
        """
        try:
            redis = await get_redis_client()
            acquired = await redis.asetNx(
                LAST_USED_THROTTLE_KEY.format(credential_id), 1, expiration=LAST_USED_THROTTLE_SECONDS
            )
        except (RedisError, OSError) as exc:
            logger.warning("open_api last_used throttle unavailable for credential {}: {}", credential_id, exc)
            return False
        if not acquired:
            return False

        async with get_async_db_session() as session:
            row = await ApiCredentialDao.aget(session, credential_id)
            if row is None:
                return False
            row.last_used_at = datetime.now()
            session.add(row)
            await ApiCredentialDao.aupdate_row(session, row)
            await session.commit()
        return True

    @classmethod
    async def mark_expired_lazy(cls, credential_id: int) -> bool:
        """Book ``revoke_reason='expired'`` the first time an expired key is rejected (AC-05 / AC-12).

        ``revoked_at`` stays NULL so expiry remains distinguishable from a manual
        revoke (K3). The conditional UPDATE is the idempotency latch: only the
        first caller sees ``rowcount == 1`` and writes the audit event, so a hot
        expired key does not produce one audit row per request.
        """
        async with get_async_db_session() as session:
            claimed = await ApiCredentialDao.amark_expired(session, credential_id)
            if not claimed:
                await session.rollback()
                return False
            await session.commit()
            row = await ApiCredentialDao.aget(session, credential_id)

        if row is not None:
            await cls._audit_system(AUDIT_ACTION_EXPIRE, row, extra={"reason": REVOKE_REASON_EXPIRED})
        return True

    @classmethod
    async def invalidate_cache(cls, token_hashes: Iterable[str]) -> int:
        """Delete the positive-cache entry of each hash, one key at a time (K1 / K7).

        The DB already holds the exact list of a subject's hashes, so there is no
        reason to ``SCAN`` a shared Redis — and no way for a scan pattern to hit
        another tenant's keys.
        """
        hashes = [value for value in token_hashes if value]
        if not hashes:
            return 0
        redis = await get_redis_client()
        deleted = 0
        for token_hash in hashes:
            deleted += bool(await redis.adelete(CREDENTIAL_CACHE_KEY.format(token_hash)))
        logger.bind(event="open_api.cache.invalidate").debug(
            "open_api.cache.invalidate keys={} deleted={}", len(hashes), deleted
        )
        return deleted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _acting_tenant_id(cls, operator: UserPayload) -> int:
        """The tenant a management write lands in: the F019 admin-scope view when set, else the operator's."""
        return get_current_tenant_id() or operator.tenant_id or DEFAULT_TENANT_ID

    @classmethod
    def _row_metadata(cls, row: ApiCredential) -> dict[str, Any]:
        """Audit payload of one key — mask only, never the plaintext (AC-12)."""
        return {
            "key_id": row.id,
            "key_mask": mask_key(row.last4, row.key_prefix),
            "name": row.name,
            "scopes": list(row.scopes or []),
            "subject_kind": row.subject_kind,
            "subject_id": row.subject_id,
            "expires_at": _iso(row.expires_at),
        }

    @classmethod
    async def _audit(
        cls,
        operator: UserPayload,
        action: str,
        row: ApiCredential,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        metadata = cls._row_metadata(row)
        if extra:
            metadata.update(extra)
        await AuditLogDao.ainsert_v2(
            tenant_id=row.tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=cls._acting_tenant_id(operator),
            action=action,
            target_type=AUDIT_TARGET_TYPE,
            target_id=str(row.id),
            metadata=metadata,
            object_name=row.name,
        )

    @classmethod
    async def _audit_subject(
        cls,
        operator: UserPayload,
        action: str,
        subject_kind: str,
        subject_id: str,
        rows: Sequence[ApiCredential],
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """One event for a whole-subject operation, listing the affected masks."""
        metadata: dict[str, Any] = {
            "subject_kind": subject_kind,
            "subject_id": str(subject_id),
            "key_masks": [mask_key(row.last4, row.key_prefix) for row in rows],
            "key_ids": [row.id for row in rows],
        }
        if extra:
            metadata.update(extra)
        tenant_id = rows[0].tenant_id if rows else cls._acting_tenant_id(operator)
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=cls._acting_tenant_id(operator),
            action=action,
            target_type=AUDIT_TARGET_TYPE,
            target_id=str(subject_id),
            metadata=metadata,
        )

    @classmethod
    async def _audit_system(cls, action: str, row: ApiCredential, *, extra: dict[str, Any] | None = None) -> None:
        """System-triggered event (``operator_id=0`` → ``operator_name='system'``)."""
        metadata = cls._row_metadata(row)
        if extra:
            metadata.update(extra)
        await AuditLogDao.ainsert_v2(
            tenant_id=row.tenant_id,
            operator_id=0,
            operator_tenant_id=DEFAULT_TENANT_ID,
            action=action,
            target_type=AUDIT_TARGET_TYPE,
            target_id=str(row.id),
            metadata=metadata,
            object_name=row.name,
        )
