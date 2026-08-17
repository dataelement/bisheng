"""``api_credential`` — hashed ``bs-sak-`` credentials (F049 design D2 / §4.2).

Facts that are easy to get wrong (design K3 / K5 / K6):

* There is **no status column**. Validity is a predicate over two timestamps —
  ``revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now)`` — see
  :meth:`ApiCredential.is_valid_at`. ``revoke_reason`` alone may be set to
  ``'expired'`` (lazy expiry bookkeeping) while ``revoked_at`` stays NULL, so
  never derive validity from ``revoke_reason``.
* Only the SHA-256 of the plaintext is stored (``token_hash``); ``key_prefix``
  + ``last4`` exist solely to render the mask ``bs-sak-********xxxx``.
* ``scopes`` is ``JsonType`` — CLOB on DM8, so scope checks happen in Python
  after the row is loaded, never in SQL.
* The DAO is single-row ORM only (no bulk ``update()`` / ``delete()`` and no
  ``text()``): the tenant filter rewrites SELECT statements only. Lookups by
  hash run before any tenant context exists, so the *caller* wraps
  :meth:`ApiCredentialDao.aget_by_hash` in ``bypass_tenant_filter()``.
* Every DAO method takes the caller's ``AsyncSession`` — the service owns the
  transaction (issue / revoke / batch revoke are multi-statement units).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, text
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

# Credential wire format (design §4.2). The prefix is public: secret-scanning
# rule ``\bbs-sak-[A-Za-z0-9_-]{43}\b``.
KEY_PREFIX = "bs-sak-"
KEY_SECRET_LENGTH = 43  # ``secrets.token_urlsafe(32)`` → 43 urlsafe chars
KEY_MASK_FILL = "********"

# ``subject_kind`` values. F049 registers a resolver for ``service_account``
# only; ``hosted_app`` rows can be issued / revoked / stored (F055 defines their
# runtime identity), ``share_link`` never has a credential row (share-token
# channel, D8) but is a valid principal kind.
SUBJECT_KIND_SERVICE_ACCOUNT = "service_account"
SUBJECT_KIND_HOSTED_APP = "hosted_app"
SUBJECT_KIND_SHARE_LINK = "share_link"
CREDENTIAL_SUBJECT_KINDS: frozenset[str] = frozenset({SUBJECT_KIND_SERVICE_ACCOUNT, SUBJECT_KIND_HOSTED_APP})

# ``revoke_reason`` values (design §4.2). ``expired`` is written lazily on the
# first rejected call after ``expires_at`` (or by the Beat sweeper) with
# ``revoked_at`` left NULL so expiry stays distinguishable from manual revoke.
REVOKE_REASON_MANUAL = "manual"
REVOKE_REASON_BATCH = "batch"
REVOKE_REASON_SUBJECT_DISABLED = "subject_disabled"
REVOKE_REASON_SUBJECT_DELETED = "subject_deleted"
REVOKE_REASON_EXPIRED = "expired"


def mask_key(last4: str, key_prefix: str = KEY_PREFIX) -> str:
    """Render the only representation of a key that ever leaves the issue response."""
    return f"{key_prefix}{KEY_MASK_FILL}{last4}"


class ApiCredential(SQLModelSerializable, table=True):
    """One issued credential. Rows are never deleted — revoke is soft (AC-11)."""

    __tablename__ = "api_credential"
    __table_args__ = (Index("ix_api_credential_subject", "tenant_id", "subject_kind", "subject_id"),)

    id: int | None = Field(default=None, primary_key=True)
    # ``default=None`` on purpose (guard test_tenant_id_default_guard): the
    # before_flush hook auto-fills from the current tenant context; a Python
    # default would silently write child-tenant rows to Root.
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    subject_kind: str = Field(
        sa_column=Column(String(32), nullable=False, comment="service_account | hosted_app"),
    )
    subject_id: str = Field(
        sa_column=Column(String(64), nullable=False, comment="service_account: user_id; hosted_app: app id"),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False, comment="Display name chosen at issue time"))
    key_prefix: str = Field(sa_column=Column(String(16), nullable=False, comment="e.g. bs-sak-"))
    last4: str = Field(sa_column=Column(String(4), nullable=False, comment="Last 4 chars of the secret"))
    token_hash: str = Field(
        sa_column=Column(
            String(64), nullable=False, unique=True, comment="sha256(plaintext) hex — the only stored form"
        ),
    )
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False, comment="Granted scope codes (list[str]); checked in Python"),
    )
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    revoke_reason: str | None = Field(
        default=None,
        sa_column=Column(
            String(32), nullable=True, comment="manual | batch | subject_disabled | subject_deleted | expired"
        ),
    )
    created_by: int | None = Field(default=None, sa_column=Column(Integer, nullable=True, comment="Issuer user id"))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )

    def is_valid_at(self, now: datetime) -> bool:
        """The single validity predicate (design K3). Boundary ``expires_at == now`` is expired."""
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now

    @property
    def key_mask(self) -> str:
        return mask_key(self.last4, self.key_prefix)


class ApiCredentialDao:
    """Single-row ORM access. Sessions and tenant-filter bypass are the caller's job."""

    @classmethod
    async def acreate(cls, session: AsyncSession, row: ApiCredential) -> ApiCredential:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aget(cls, session: AsyncSession, credential_id: int) -> ApiCredential | None:
        result = await session.exec(select(ApiCredential).where(ApiCredential.id == credential_id))
        return result.first()

    @classmethod
    async def aget_by_hash(cls, session: AsyncSession, token_hash: str) -> ApiCredential | None:
        """Lookup by ``sha256(plaintext)``.

        Runs before any tenant context exists — the caller MUST wrap it in
        ``bypass_tenant_filter()`` (design K6); the row's ``tenant_id`` is what
        the validator then seeds into the tenant ContextVar (K9).
        """
        result = await session.exec(select(ApiCredential).where(ApiCredential.token_hash == token_hash))
        return result.first()

    @classmethod
    async def alist_by_subject(
        cls,
        session: AsyncSession,
        subject_kind: str,
        subject_id: str,
        *,
        include_revoked: bool = True,
    ) -> list[ApiCredential]:
        """All credentials of one subject, newest first. Tenant scoping comes from the auto filter."""
        statement = select(ApiCredential).where(
            ApiCredential.subject_kind == subject_kind,
            ApiCredential.subject_id == str(subject_id),
        )
        if not include_revoked:
            statement = statement.where(col(ApiCredential.revoked_at).is_(None))
        statement = statement.order_by(col(ApiCredential.id).desc())
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def aupdate_row(cls, session: AsyncSession, row: ApiCredential) -> ApiCredential:
        """Persist in-place changes of one row (soft revoke, scope edit, last_used_at, ...)."""
        row.update_time = datetime.now()
        session.add(row)
        await session.flush()
        return row
