"""Platform-owned cross-tenant Kunlian keys; deliberately not ApiCredential."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.open_api.domain.models.api_credential import mask_key

KUNLIAN_KEY_PREFIX = "bs-kl-"
KUNLIAN_ALL_TENANTS_WILDCARD = "*"
KUNLIAN_CAPABILITIES = frozenset({"read", "write", "publish", "invoke", "grant"})


class KunlianCredential(SQLModelSerializable, table=True):
    # Global integration metadata: no local tenant_id and no tenant-filter bypass
    # is inherited by business operations.
    __tablename__ = "kunlian_credential"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    integration_id: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    connection_id: str = Field(sa_column=Column(String(128), nullable=False))
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True), repr=False)
    last4: str = Field(sa_column=Column(String(4), nullable=False))
    tenant_ids: list[str] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    capabilities: list[str] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    policy_revision: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    rotated_from_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    created_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )

    @property
    def key_mask(self) -> str:
        return mask_key(self.last4, KUNLIAN_KEY_PREFIX)
