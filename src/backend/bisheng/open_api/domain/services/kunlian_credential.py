"""Kunlian-only key lifecycle. Callers supply trusted local super-admin status."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger

from bisheng.open_api.domain.models.kunlian_credential import (
    KUNLIAN_ALL_TENANTS_WILDCARD,
    KUNLIAN_CAPABILITIES,
    KUNLIAN_KEY_PREFIX,
    KunlianCredential,
)
from bisheng.open_api.domain.repositories.kunlian_credential import KunlianCredentialRepository


class KunlianAccessError(Exception):
    """Transport-neutral classification; never includes request secrets."""

    def __init__(self, code):
        self.code = code
        self.http_status = {
            "UNAUTHENTICATED": 401,
            "FORBIDDEN": 403,
            "NOT_FOUND": 404,
            "CONFLICT": 409,
            "INVALID_INPUT": 422,
            "UNAVAILABLE": 503,
        }[code]
        super().__init__(code)


@dataclass(frozen=True)
class KunlianCaller:
    credential_id: int
    integration_id: str
    connection_id: str
    capabilities: frozenset[str]
    policy_revision: int
    tenant_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KunlianPrincipal:
    credential_id: int
    integration_id: str
    connection_id: str
    external_tenant_id: str
    capabilities: frozenset[str]
    policy_revision: int


def _utc(value):
    # DB DateTime is UTC without timezone on MySQL/DM8; public inputs may be aware.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _expiry(value):
    if value is None:
        return None
    if not isinstance(value, datetime) or _utc(value) <= datetime.now(UTC):
        raise KunlianAccessError("INVALID_INPUT")
    return _utc(value).replace(tzinfo=None)


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise KunlianAccessError("INVALID_INPUT")
    return value


def _scope(values, *, capabilities=False):
    if not isinstance(values, (list, tuple)) or not values or len(values) > 1000:
        raise KunlianAccessError("INVALID_INPUT")
    result = list(dict.fromkeys(_identifier(value) for value in values))
    if capabilities:
        if not set(result) <= KUNLIAN_CAPABILITIES:
            raise KunlianAccessError("INVALID_INPUT")
        return result
    if KUNLIAN_ALL_TENANTS_WILDCARD in result and len(result) > 1:
        raise KunlianAccessError("INVALID_INPUT")
    return result


def _allows_tenant(tenant_ids, external_tenant_id):
    if not isinstance(external_tenant_id, str) or not external_tenant_id:
        return False
    return KUNLIAN_ALL_TENANTS_WILDCARD in tenant_ids or external_tenant_id in tenant_ids


_UNSET = object()


class KunlianCredentialService:
    def __init__(self, store=None):
        self.store = store if store is not None else KunlianCredentialRepository()

    @staticmethod
    def _super(is_global_super):
        if is_global_super is not True:
            raise KunlianAccessError("FORBIDDEN")

    async def _call(self, method, *args, **kwargs):
        try:
            return await getattr(self.store, method)(*args, **kwargs)
        except Exception:
            # Do not log exception text/traceback: a driver can include bound key
            # hashes or metadata. Classification is sufficient for alerting.
            logger.error("Kunlian credential repository {} failed; access denied", method)
            raise KunlianAccessError("UNAVAILABLE") from None

    @staticmethod
    def _item(row):
        return {
            name: getattr(row, name)
            for name in (
                "id",
                "integration_id",
                "connection_id",
                "policy_revision",
                "expires_at",
                "revoked_at",
                "created_by",
                "create_time",
                "rotated_from_id",
            )
        } | {"tenant_ids": list(row.tenant_ids), "capabilities": list(row.capabilities), "key_mask": row.key_mask}

    @staticmethod
    def _new(
        *, created_by, connection_id, integration_id, tenant_ids, capabilities, expires_at=None, rotated_from_id=None
    ):
        if type(created_by) is not int or created_by <= 0:
            raise KunlianAccessError("INVALID_INPUT")
        connection_id, integration_id = _identifier(connection_id), _identifier(integration_id)
        tenants, capabilities = _scope(tenant_ids), _scope(capabilities, capabilities=True)
        expires_at = _expiry(expires_at)
        plaintext = KUNLIAN_KEY_PREFIX + secrets.token_urlsafe(32)
        row = KunlianCredential(
            created_by=created_by,
            connection_id=connection_id,
            integration_id=integration_id,
            tenant_ids=tenants,
            capabilities=capabilities,
            expires_at=expires_at,
            token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
            last4=plaintext[-4:],
            rotated_from_id=rotated_from_id,
        )
        return row, plaintext

    async def issue(
        self, *, is_global_super, created_by, connection_id, integration_id, tenant_ids, capabilities, expires_at=None
    ):
        self._super(is_global_super)
        row, plaintext = self._new(
            created_by=created_by,
            connection_id=connection_id,
            integration_id=integration_id,
            tenant_ids=tenant_ids,
            capabilities=capabilities,
            expires_at=expires_at,
        )
        row = await self._call("insert", row)
        return self._item(row) | {"api_key": plaintext}

    async def authenticate_caller(self, authorization, *, capability):
        """Verify transport credentials before resolving an account or selecting a tenant."""
        row = await self._authenticate_row(authorization, capability=capability)
        return KunlianCaller(
            row.id,
            row.integration_id,
            row.connection_id,
            frozenset(row.capabilities),
            row.policy_revision,
            tuple(row.tenant_ids),
        )

    async def authenticate(self, authorization, *, external_tenant_id, capability):
        row = await self._authenticate_row(authorization, capability=capability)
        if not _allows_tenant(row.tenant_ids, external_tenant_id):
            raise KunlianAccessError("FORBIDDEN")
        return KunlianPrincipal(
            row.id,
            row.integration_id,
            row.connection_id,
            external_tenant_id,
            frozenset(row.capabilities),
            row.policy_revision,
        )

    async def _authenticate_row(self, authorization, *, capability):
        match = (
            re.fullmatch(r"(?i:Bearer) (bs-kl-[A-Za-z0-9_-]{43})", authorization or "")
            if isinstance(authorization, (str, type(None)))
            else None
        )
        if match is None:
            raise KunlianAccessError("UNAUTHENTICATED")
        digest = hashlib.sha256(match[1].encode()).hexdigest()
        row = await self._call("by_hash", digest)
        if (
            row is None
            or not secrets.compare_digest(row.token_hash, digest)
            or row.revoked_at is not None
            or (row.expires_at is not None and _utc(row.expires_at) <= datetime.now(UTC))
        ):
            raise KunlianAccessError("UNAUTHENTICATED")
        if capability not in KUNLIAN_CAPABILITIES or capability not in row.capabilities:
            raise KunlianAccessError("FORBIDDEN")
        return row

    async def validate_reference(
        self, credential_id, *, integration_id, connection_id, external_tenant_id, capability
    ) -> KunlianPrincipal:
        """Revalidate a trusted persisted worker reference, never an HTTP identity.

        The reference must originate from successful bearer admission. This
        internal port is not an alternative public authentication mechanism.
        """
        if type(credential_id) is not int or credential_id <= 0:
            raise KunlianAccessError("UNAUTHENTICATED")
        row = await self._call("get", credential_id)
        if (
            row is None
            or row.revoked_at is not None
            or (row.expires_at is not None and _utc(row.expires_at) <= datetime.now(UTC))
        ):
            raise KunlianAccessError("UNAUTHENTICATED")
        if (
            row.integration_id != integration_id
            or row.connection_id != connection_id
            or capability not in KUNLIAN_CAPABILITIES
            or capability not in row.capabilities
            or not _allows_tenant(row.tenant_ids, external_tenant_id)
        ):
            raise KunlianAccessError("FORBIDDEN")
        return KunlianPrincipal(
            row.id,
            row.integration_id,
            row.connection_id,
            external_tenant_id,
            frozenset(row.capabilities),
            row.policy_revision,
        )

    async def _get(self, key_id):
        if type(key_id) is not int or key_id <= 0:
            raise KunlianAccessError("INVALID_INPUT")
        row = await self._call("get", key_id)
        if row is None:
            raise KunlianAccessError("NOT_FOUND")
        # Never mutate an authoritative object before a successful write (fake
        # stores and ORM identity maps may retain the original instance).
        return KunlianCredential(**{name: getattr(row, name) for name in KunlianCredential.model_fields})

    async def _save(self, row):
        previous = row.policy_revision
        row.policy_revision += 1
        if not await self._call("save", row, expected_revision=previous):
            raise KunlianAccessError("CONFLICT")
        return self._item(row)

    async def revoke(self, key_id, *, is_global_super):
        self._super(is_global_super)
        row = await self._get(key_id)
        if row.revoked_at is not None:
            return self._item(row)
        row.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        return await self._save(row)

    async def update(self, key_id, *, is_global_super, tenant_ids=_UNSET, capabilities=_UNSET, expires_at=_UNSET):
        self._super(is_global_super)
        row = await self._get(key_id)
        if row.revoked_at is not None:
            raise KunlianAccessError("CONFLICT")
        if tenant_ids is not _UNSET:
            row.tenant_ids = _scope(tenant_ids)
        if capabilities is not _UNSET:
            row.capabilities = _scope(capabilities, capabilities=True)
        if expires_at is not _UNSET:
            row.expires_at = _expiry(expires_at)
        return await self._save(row)

    async def rotate(self, key_id, *, is_global_super, created_by=None):
        self._super(is_global_super)
        old = await self._get(key_id)
        if old.revoked_at is not None:
            raise KunlianAccessError("CONFLICT")
        new, plaintext = self._new(
            created_by=created_by if created_by is not None else old.created_by,
            connection_id=old.connection_id,
            integration_id=old.integration_id,
            tenant_ids=old.tenant_ids,
            capabilities=old.capabilities,
            expires_at=old.expires_at,
            rotated_from_id=old.id,
        )
        previous = old.policy_revision
        old.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        old.policy_revision += 1
        new = await self._call("rotate", old, new, expected_revision=previous)
        if new is None:
            raise KunlianAccessError("CONFLICT")
        return self._item(new) | {"api_key": plaintext}

    async def detail(self, key_id, *, is_global_super):
        """Return control-plane metadata, including revoked keys, never secrets."""
        self._super(is_global_super)
        return self._item(await self._get(key_id))

    async def list(self, *, is_global_super, offset=0, limit=100):
        self._super(is_global_super)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise KunlianAccessError("INVALID_INPUT")
        return [self._item(row) for row in await self._call("list", offset=offset, limit=limit)]
