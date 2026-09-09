"""Hashed credentials accepted by the ``/api/v2`` Open API surface."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

SERVICE_ACCOUNT_KEY_PREFIX = "bs-sak-"
PERSONAL_TOKEN_PREFIX = "bs-pat-"
KEY_SECRET_LENGTH = 43
KEY_MASK_FILL = "********"

SUBJECT_KIND_SERVICE_ACCOUNT = "service_account"
SUBJECT_KIND_NATURAL_PERSON = "natural_person"
CREDENTIAL_SUBJECT_KINDS = frozenset({SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_KIND_NATURAL_PERSON})

REVOKE_REASON_MANUAL = "manual"
REVOKE_REASON_BATCH = "batch"
REVOKE_REASON_REISSUED = "reissued"
REVOKE_REASON_REGENERATED = "regenerated"
REVOKE_REASON_SUBJECT_DISABLED = "subject_disabled"
REVOKE_REASON_SUBJECT_DELETED = "subject_deleted"
REVOKE_REASON_TENANT_CHANGED = "tenant_changed"


def mask_key(last4: str, key_prefix: str) -> str:
    """Return the only credential representation exposed after issuance."""

    return f"{key_prefix}{KEY_MASK_FILL}{last4}"


class ApiCredential(SQLModelSerializable, table=True):
    """Credential metadata; plaintext key material is never persisted."""

    __tablename__ = "api_credential"
    __table_args__ = (
        CheckConstraint(
            "subject_kind IN ('service_account', 'natural_person')",
            name="ck_api_credential_subject_kind",
        ),
        Index("idx_api_credential_subject", "tenant_id", "subject_kind", "subject_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    subject_kind: str = Field(
        sa_column=Column(String(32), nullable=False, comment="service_account | natural_person"),
    )
    subject_id: int = Field(
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"), nullable=False, comment="Typed subject identifier"
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False, comment="Credential display name"))
    key_prefix: str = Field(sa_column=Column(String(16), nullable=False))
    last4: str = Field(sa_column=Column(String(4), nullable=False))
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, comment="SHA-256 hex digest"),
    )
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False, comment="Granted Open API scopes"),
    )
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    revoke_reason: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    created_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )

    def is_valid_at(self, now: datetime) -> bool:
        """Return whether this row is active at ``now``; expiry is exclusive."""

        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)

    @property
    def key_mask(self) -> str:
        return mask_key(self.last4, self.key_prefix)
